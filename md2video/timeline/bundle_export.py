"""timeline + run 产物 → 混剪素材包（解法 4，交付形态）。

bundle 是 run 已有事实面向消费级剪辑软件的再序列化，不产生新事实：

- subtitles.srt : text cue 中口播类（SRT_SEGMENT_TYPES 白名单）→ 字幕轨；
  标题/节标题是全程挂屏文字而非口播，不进字幕。
- timeline.edl  : 复用 otio lowering 转 CMX3600，专业 NLE 的剪辑骨架。
- clips/        : 按 shots 边界重编码切成片。不用流拷贝——它按关键帧切，
  边界会漂移半秒，用户在剪辑软件里对不齐；重编码帧级精确且与渲染后端
  无关（manim/remotion 的成片都在同一时间轴上）。
- assets/       : 媒体声明解析后的原始图片 / BGM 与每段配音（execution
  assets 的拷贝），供替换与重排。

永不抛错：任何一部分失败折进 warnings 由调用方并入 run warnings；成片
是第一交付物，bundle 失败不阻断交付。文本产物（srt/edl/README）确定性
逐字节可复现；clips 是重编码视频，只保证属性不保证字节。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from md2video.timeline.otio_export import (
    DEFAULT_TIMELINE_FPS,
    _finite,
    _shot_intervals,
    _shot_id_of,
)

BUNDLE_DIRNAME = "bundle"
SRT_FILENAME = "subtitles.srt"
EDL_FILENAME = "timeline.edl"
README_FILENAME = "README.txt"

# 口播类文本才进字幕；title_main/title_sub/section_header 是挂屏文字
SRT_SEGMENT_TYPES = frozenset({"content", "appendix"})

README_TEXT = """\
markdown2video 混剪素材包
=========================

- clips/shot_*.mp4          按 shot 边界切好的成片片段，按文件名顺序
                            排列即完整成片
- subtitles.srt             口播字幕（剪映 / 必剪 / Premiere / Resolve
                            均可导入）；画面已含渲染文字，按需选用
- timeline.edl              剪辑时间线骨架（CMX3600，专业 NLE 可导入）
- assets/images|music|audio 原始素材：图片、BGM、每段配音，供替换或重排

本目录由 markdown2video 自动生成，可任意使用与修改。
"""


def _seconds_to_srt_time(value: float) -> str:
    """秒 → SRT 时码 HH:MM:SS,mmm（逗号分隔毫秒，负值截到 0）。"""
    total_ms = int(round(max(0.0, value) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_srt(timeline_data: dict) -> str:
    """口播类 text cue → SRT 文本；按 start 排序；坏条目跳过不抛错。"""
    entries = []
    for entry in timeline_data.get("text") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("segment_type") not in SRT_SEGMENT_TYPES:
            continue
        start = _finite(entry.get("start"))
        end = _finite(entry.get("end"))
        text = str(entry.get("text") or "").strip()
        if start is None or end is None or end <= start or not text:
            continue
        entries.append((start, end, text))
    entries.sort(key=lambda item: (item[0], item[1]))

    blocks = []
    for index, (start, end, text) in enumerate(entries, 1):
        blocks.append(
            f"{index}\n"
            f"{_seconds_to_srt_time(start)} --> {_seconds_to_srt_time(end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def _write_edl(timeline_data: dict, out_path: Path, *, name: str = "") -> None:
    import opentimelineio as otio

    from md2video.timeline.otio_export import timeline_to_otio

    otio.adapters.write_to_file(
        timeline_to_otio(timeline_data, name=name),
        str(out_path),
        # 社区适配器 otio-cmx3600-adapter 的注册名带下划线
        adapter_name="cmx_3600",
    )


def _cut_clips(timeline_data: dict, final_video: Path, clips_dir: Path) -> str:
    """按 shots 边界把成片切成片段。返回空串或一条降级说明。"""
    video_path = Path(final_video)
    if not video_path.is_file():
        return f"final video missing ({video_path}); bundle clips skipped"

    from md2video.assembler.ffmpeg_assembler import ffprobe_duration

    total_duration = ffprobe_duration(video_path)
    min_duration = 1.0 / DEFAULT_TIMELINE_FPS
    for start, end, entry in _shot_intervals(timeline_data.get("shots") or []):
        end = min(end, total_duration)
        if end - start <= min_duration:
            continue
        shot_id = _shot_id_of(entry) or f"shot_{start:.3f}"
        safe_name = "".join(
            ch if (ch.isalnum() or ch in "._-") else "_" for ch in shot_id
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{max(0.0, start):.3f}",
            "-i", str(video_path),
            "-t", f"{end - start:.3f}",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            str(clips_dir / f"{safe_name}.mp4"),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    return ""


def _copy_existing(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _audio_suffix(path: Path) -> str:
    """按内容魔数识别音频容器扩展名。

    edge-tts 的产物可能名不副实（请求 .wav 但字节是 mp3）；消费级剪辑
    软件按扩展名验格式，扩展名说谎会被静默拒收（必剪实测），所以拷贝
    进 bundle 前先纠正。识别不出时保留原扩展名。
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
    except OSError:
        return path.suffix or ".wav"
    if head[:3] == b"ID3" or (
        len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    ):
        return ".mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"OggS":
        return ".ogg"
    if head[:4] == b"fLaC":
        return ".flac"
    return path.suffix or ".wav"


def _copy_assets(plan, execution_assets, base_dir, assets_dir: Path) -> None:
    base = Path(base_dir) if base_dir else None

    def resolved(src) -> Path:
        path = Path(str(src))
        if not path.is_absolute() and base is not None:
            path = base / path
        return path

    if plan is not None:
        declarations = getattr(plan, "media_declarations", None) or {}
        for name, src in (declarations.get("images") or {}).items():
            src_path = resolved(src)
            _copy_existing(src_path, assets_dir / "images" / f"{name}{src_path.suffix}")
        for name, src in (declarations.get("music") or {}).items():
            src_path = resolved(src)
            _copy_existing(src_path, assets_dir / "music" / f"{name}{src_path.suffix}")

    if execution_assets is not None:
        for asset in getattr(execution_assets, "audio_assets", []) or []:
            src_path = Path(str(asset.path))
            _copy_existing(
                src_path,
                assets_dir / "audio" / f"{asset.segment_id}{_audio_suffix(src_path)}",
            )


def export_bundle(
    timeline_data: dict,
    final_video: Path,
    out_dir: Path,
    *,
    plan=None,
    execution_assets=None,
    base_dir: Path | None = None,
    run_name: str = "",
) -> tuple[Path | None, list[str]]:
    """导出混剪素材包，返回 (目录, warnings)；失败不抛错只折进 warnings。"""
    warnings: list[str] = []
    out_dir = Path(out_dir)
    try:
        (out_dir / "clips").mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return None, [f"bundle export failed: {exc}"]

    try:
        (out_dir / SRT_FILENAME).write_text(
            build_srt(timeline_data), encoding="utf-8",
        )
    except Exception as exc:
        warnings.append(f"bundle srt failed: {exc}")

    try:
        _write_edl(timeline_data, out_dir / EDL_FILENAME, name=run_name)
    except ImportError:
        warnings.append("opentimelineio not installed; bundle edl skipped")
    except Exception as exc:
        warnings.append(f"bundle edl failed: {exc}")

    try:
        (out_dir / README_FILENAME).write_text(README_TEXT, encoding="utf-8")
    except Exception as exc:
        warnings.append(f"bundle readme failed: {exc}")

    try:
        clip_warning = _cut_clips(timeline_data, Path(final_video), out_dir / "clips")
        if clip_warning:
            warnings.append(clip_warning)
    except Exception as exc:
        warnings.append(f"bundle clips failed: {exc}")

    try:
        _copy_assets(plan, execution_assets, base_dir, out_dir / "assets")
    except Exception as exc:
        warnings.append(f"bundle assets failed: {exc}")

    return out_dir, warnings
