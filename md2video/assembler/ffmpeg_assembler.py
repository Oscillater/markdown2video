"""
FFmpeg Assembler - 消费 Result Manifest + Plan Manifest，合成最终视频。

不再重新解析 markdown，所有数据来自 manifest。
"""
from __future__ import annotations

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple

from md2video.layout.mapping import box_pixel_rect, even_size
from md2video.layout.resolve import resolve_scene_layout
from md2video.manifest.schema import (
    ExecutionAssets,
    PlanManifest,
    ResultManifest,
    result_manifest_from_execution_assets,
)


# ========== Ken Burns 动效 ==========

def _build_ken_burns_filter(
    input_label: str, output_label: str,
    duration: float, width: int, height: int,
    zoom_speed: float = 0.001, zoom_direction: str = "in", fps: int = 30,
) -> str:
    """构建 ffmpeg zoompan 滤镜字符串。"""
    total_frames = int(duration * fps)
    if zoom_direction == "out":
        zoom_expr = f"if(eq(on,1),1.5,max(zoom-{zoom_speed},1.0))"
    else:
        zoom_expr = f"min(zoom+{zoom_speed},1.5)"
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"
    return (
        f"{input_label}"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={total_frames}:s={width}x{height}:fps={fps}"
        f"{output_label}"
    )


# ========== ffmpeg helpers ==========

def run(cmd, check=True):
    print("RUN:", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def ffprobe_resolution(path: Path) -> Tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    # Remotion 产出的 mp4 会多带一个尾部空字段（如 "480x854x"），只取前两段
    width, height = (int(v) for v in p.stdout.strip().split("x")[:2])
    return width, height


def ffprobe_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    return float(p.stdout.strip())


def has_audio_stream(path: Path) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return bool(p.stdout.strip())


def prepare_audio_segment(src: Path, duration: float, out_path: Path,
                          trim_silence: bool = True, fade_in: float = 2.0):
    use_src = src
    tmp_trim = None
    if trim_silence:
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_trim = Path(tmpf.name)
        tmpf.close()
        cmd_trim = [
            "ffmpeg", "-y", "-i", str(src),
            "-af", "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB",
            "-ac", "2", "-ar", "44100", "-vn", str(tmp_trim)
        ]
        run(cmd_trim)
        if tmp_trim.exists() and tmp_trim.stat().st_size > 100:
            use_src = tmp_trim
        else:
            try:
                if tmp_trim.exists():
                    tmp_trim.unlink()
                tmp_trim = None
            except Exception:
                tmp_trim = None

    af_filters = []
    if fade_in and fade_in > 0 and duration > 0:
        fd = min(fade_in, duration)
        af_filters.append(f"afade=t=in:st=0:d={fd:.3f}")

    af_chain = ",".join(af_filters) if af_filters else None
    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(use_src),
           "-t", f"{duration:.3f}", "-ac", "2", "-ar", "44100", "-vn"]
    if af_chain:
        cmd.extend(["-af", af_chain])
    cmd.append(str(out_path))
    run(cmd)

    if tmp_trim and tmp_trim.exists():
        try:
            tmp_trim.unlink()
        except Exception:
            pass


# ========== 从 Manifest 提取媒体时间 ==========

def _load_marker_timeline(timeline_path: Path) -> Dict[str, float]:
    """从 timeline.json 加载 marker 的实际视频时间。"""
    if not timeline_path or not timeline_path.exists():
        return {}
    import json as _json
    data = _json.loads(timeline_path.read_text(encoding="utf-8"))
    markers = data.get("markers", [])
    return {
        m.get("segment_id") or m.get("id"): m["time"]
        for m in markers
        if (m.get("segment_id") or m.get("id")) and "time" in m
    }


def _iter_marker_cues(plan: PlanManifest, cue_type: str):
    for scene in plan.scenes:
        for shot in scene.shots:
            for cue in shot.cues:
                if cue.get("cue_type") == cue_type:
                    yield cue


def _marker_cue_time(cue: Dict[str, Any], marker_times: Dict[str, float]) -> float:
    cue_id = cue.get("id")
    if not cue_id or cue_id not in marker_times:
        raise ValueError(f"Timeline missing marker cue time: {cue_id}")
    return float(marker_times[cue_id])


def _load_shot_timeline(timeline_path: Path) -> Dict[str, Tuple[float, float]]:
    """Load actual shot timing from renderer timeline.json."""
    if not timeline_path or not timeline_path.exists():
        return {}
    import json as _json
    data = _json.loads(timeline_path.read_text(encoding="utf-8"))

    timing: Dict[str, Tuple[float, float]] = {}
    for shot in data.get("shots", []):
        shot_id = shot.get("shot_id")
        if not shot_id or shot.get("end") is None:
            continue
        timing[shot_id] = (float(shot["start"]), float(shot["end"]))
    return timing


def extract_music_entries(plan: PlanManifest, result: ResultManifest,
                           timeline_path: Path = None) -> List[Dict]:
    """从 Manifest 中提取音乐时间段。使用 timeline.json 中的实际视频时间。"""
    music_map = plan.media_declarations.get("music", {})
    marker_times = _load_marker_timeline(timeline_path)
    entries = []

    for cue in _iter_marker_cues(plan, "marker_music"):
        kind = cue.get("kind", "")
        name = cue.get("name", "")
        src = music_map.get(name)
        actual_time = _marker_cue_time(cue, marker_times)

        if kind == "start":
            entries.append({
                "name": name,
                "src": src,
                "start": float(actual_time),
                "end": None,
            })
        elif kind == "end":
            # 回填 start
            for entry in reversed(entries):
                if entry["name"] == name and entry["end"] is None:
                    entry["end"] = float(actual_time)
                    break

    return entries


def extract_image_entries(plan: PlanManifest, result: ResultManifest,
                           timeline_path: Path = None) -> List[Dict]:
    """从 Manifest 中提取图片时间段。使用 timeline.json 中的实际视频时间。"""
    image_map = plan.media_declarations.get("images", {})
    marker_times = _load_marker_timeline(timeline_path)
    entries = []

    for cue in _iter_marker_cues(plan, "marker_image"):
        kind = cue.get("kind", "")
        name = cue.get("name", "")
        src = image_map.get(name)
        actual_time = _marker_cue_time(cue, marker_times)

        if kind == "start":
            entries.append({
                "name": name,
                "src": src,
                "start": float(actual_time),
                "end": None,
            })
        elif kind == "end":
            for entry in reversed(entries):
                if entry["name"] == name and entry["end"] is None:
                    entry["end"] = float(actual_time)
                    break

    return entries


def extract_shot_visual_entries(result: ResultManifest) -> List[Dict]:
    """从 result.scenes[].shots[].visual 中提取 per-shot 视觉产物条目。"""
    entries = []
    for scene_result in result.scenes:
        for shot_result in scene_result.shots:
            vis = shot_result.visual
            if vis.path and vis.source != "none":
                entries.append({
                    "name": shot_result.id,
                    "src": vis.path,
                    "start": shot_result.start,
                    "end": shot_result.end,
                })
    return entries


# ========== ffmpeg 合成 ==========

# Ken Burns 抖动治理：zoompan 的 x/y/zoom 按输入像素格点取整，直接在目标
# 分辨率上做会逐帧跳变。先把图超采样放大再 zoompan（输出尺寸不变），
# 亚像素运动才保得住。
KB_SUPERSAMPLE = 4


def _kb_supersample_size(region_w: int, region_h: int) -> Tuple[int, int]:
    """zoompan 输入的超采样尺寸（4 倍，带上限防性能炸裂）。"""
    return (
        min(region_w * KB_SUPERSAMPLE, 3840),
        min(region_h * KB_SUPERSAMPLE, 6144),
    )


def extract_shot_visual_entries_from_assets(
    plan: PlanManifest,
    execution_assets: ExecutionAssets,
    result: ResultManifest | None = None,
    timeline_path: Path | None = None,
) -> List[Dict]:
    """Extract per-shot visual overlay entries from execution-assets.

    Each entry carries its scene layout contract so the overlay can be placed
    by the same LayoutTemplate the renderer used.
    """
    result = result or result_manifest_from_execution_assets(plan, execution_assets)
    shot_timing = _load_shot_timeline(timeline_path)
    fallback_timing = {
        shot.id: (shot.start, shot.end)
        for scene in result.scenes
        for shot in scene.shots
    }
    scene_by_shot = {
        shot.id: scene
        for scene in plan.scenes
        for shot in scene.shots
    }

    entries = []
    for asset in execution_assets.visual_assets:
        if not asset.path or asset.provider == "none":
            continue
        start, end = shot_timing.get(
            asset.shot_id,
            fallback_timing.get(asset.shot_id, (0.0, 0.0)),
        )
        entry = {
            "name": asset.shot_id,
            "src": asset.path,
            "start": start,
            "end": end,
        }
        scene = scene_by_shot.get(asset.shot_id)
        if scene is not None:
            entry["layout_type"] = scene.layout_type
            entry["layout_params"] = dict(scene.layout_params)
            if scene.layout_regions:
                entry["layout_regions"] = {
                    name: dict(box) for name, box in scene.layout_regions.items()
                }
        entries.append(entry)
    return entries


def attach_image_layout_regions(
    entries: List[Dict],
    video_width: int,
    video_height: int,
    layout_registry=None,
) -> List[Dict]:
    """Attach pixel-space "image" region rects derived from each entry's layout.

    Layout resolution goes through the shared proposal/template judge so the
    assembler cannot disagree with the renderer about a scene's regions.
    Entries without a resolvable layout or without an "image" region are left
    untouched and keep the legacy overlay placement.
    """
    for entry in entries:
        layout_type = entry.get("layout_type")
        if not layout_type:
            continue
        try:
            computed = resolve_scene_layout(
                layout_type,
                entry.get("layout_params"),
                entry.get("layout_regions"),
                video_width,
                video_height,
                registry=layout_registry,
            )
        except Exception:
            continue
        if "image" not in computed.regions:
            continue
        left, top, width, height = box_pixel_rect(
            computed.region("image"), video_width, video_height,
        )
        width, height = even_size(width, height)
        if width <= 0 or height <= 0:
            continue
        entry["region_px"] = {"left": left, "top": top, "width": width, "height": height}
    return entries


def build_and_run_ffmpeg(video_path: Path, music_segments, image_segments,
                         base_has_audio: bool, out_path: Path,
                         video_duration: float, video_width: int, video_height: int,
                         gain: float = None, ken_burns_config=None,
                         subtitle_filter: str = None):

    REL_MAX_WIDTH = 0.6
    REL_MAX_HEIGHT = 0.7
    REL_CENTER_X = 0.6
    REL_CENTER_Y = 0.35

    MAX_WIDTH = int(video_width * REL_MAX_WIDTH)
    MAX_HEIGHT = int(video_height * REL_MAX_HEIGHT)
    CENTER_X = int(video_width * REL_CENTER_X)
    CENTER_Y = int(video_height * REL_CENTER_Y)

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if base_has_audio:
        base_label = "[0:a]"
        next_input_idx = 1
    else:
        cmd.extend(["-f", "lavfi", "-t", f"{video_duration:.3f}",
                     "-i", "anullsrc=cl=stereo:r=44100"])
        base_label = "[1:a]"
        next_input_idx = 2

    for seg in music_segments:
        cmd.extend(["-i", str(seg["path"])])
    img_input_base_idx = next_input_idx + len(music_segments)
    for img in image_segments:
        cmd.extend(["-i", str(img["src"])])

    audio_parts, music_labels = [], []
    for i, seg in enumerate(music_segments):
        input_idx = next_input_idx + i
        start_ms = int(round(seg["start"] * 1000))
        vol = seg.get("volume", 1.0)
        label = f"[m{i}]"
        audio_parts.append(f"[{input_idx}:a]adelay={start_ms}:all=1,volume={vol}{label}")
        music_labels.append(label)

    # 短片的 loudnorm 分析窗口不足，部分 FFmpeg 会产生 NaN；
    # 纯补静音也不需要归一化。显式 gain（包括 0）始终优先。
    if gain is not None:
        audio_effect = f"volume={gain}"
    elif video_duration < 3.0 or (not base_has_audio and not music_segments):
        audio_effect = "anull"
    else:
        audio_effect = "loudnorm"

    # 构建音频 filter
    audio_filter_parts = []
    audio_map_label = "0:a" if base_has_audio else None
    if music_segments or not base_has_audio:
        all_inputs = [base_label] + music_labels
        amix_part = "".join(all_inputs) + f"amix=inputs={len(all_inputs)}:duration=longest:dropout_transition=0[aout]"
        audio_chain = f"[aout]{audio_effect}[aout]"
        audio_filter_parts = audio_parts + [amix_part, audio_chain]
        audio_map_label = "[aout]"
    else:
        # 已有音频，无音乐，直接应用同一音量/归一化策略。
        audio_filter_parts = [f"[0:a]{audio_effect}[aout]"]
        audio_map_label = "[aout]"

    video_label = "[0:v]"
    vid_parts = []
    kb_enabled = ken_burns_config and getattr(ken_burns_config, "enabled", False)
    for i, img in enumerate(image_segments):
        img_input_stream = f"[{img_input_base_idx + i}:v]"
        start = img["start"]
        end = img["end"] if img["end"] is not None else video_duration
        duration = end - start
        out_label = f"[v{i}]"
        region = img.get("region_px")

        if kb_enabled and duration > 1.0:
            # Ken Burns: 超采样 scale(cover) → zoompan（保持超采样尺寸，取整
            # 停留在细格点上）→ 缩回目标区域（插值保住亚像素运动）→ overlay
            region_w = region["width"] if region else video_width
            region_h = region["height"] if region else video_height
            scaled_stream = f"[img{i}_scaled]"
            zoomed_stream = f"[img{i}_zoomed]"
            ss_w, ss_h = _kb_supersample_size(region_w, region_h)
            scale_filter = (
                f"{img_input_stream}scale={ss_w}:{ss_h}:"
                f"force_original_aspect_ratio=increase,setsar=1{scaled_stream}"
            )
            kb_filter = _build_ken_burns_filter(
                scaled_stream, zoomed_stream, duration,
                ss_w, ss_h,
                zoom_speed=ken_burns_config.zoom_speed,
                zoom_direction=ken_burns_config.zoom_direction,
                fps=ken_burns_config.fps,
            )
            down_stream = f"[img{i}_down]"
            down_filter = (
                f"{zoomed_stream}scale={region_w}:{region_h}:"
                f"flags=lanczos,setsar=1{down_stream}"
            )
            if region:
                overlay_pos = f"x='{region['left']}':y='{region['top']}'"
            else:
                overlay_pos = "x='(W-w)/2':y='(H-h)/2'"
            overlay_filter = (
                f"{video_label}{down_stream}"
                f"overlay={overlay_pos}:enable='between(t,{start},{end})'{out_label}"
            )
            vid_parts.extend([scale_filter, kb_filter, down_filter, overlay_filter])
        else:
            # 静态 overlay：有 layout region 时 contain 进 region，否则用旧常量
            scaled_img_stream = f"[img{i}_scaled]"
            if region:
                region_w, region_h = region["width"], region["height"]
                ratio_test = f"gt(iw/ih,{region_w}/{region_h})"
                scale_filter = (
                    f"{img_input_stream}scale=w='if({ratio_test},{region_w},-2)'"
                    f":h='if({ratio_test},-2,{region_h})',setsar=1{scaled_img_stream}"
                )
                overlay_filter = (
                    f"{video_label}{scaled_img_stream}"
                    f"overlay=x='{region['left']}+({region_w}-w)/2'"
                    f":y='{region['top']}+({region_h}-h)/2'"
                    f":enable='between(t,{start},{end})'{out_label}"
                )
            else:
                scale_filter = (
                    f"{img_input_stream}scale=w='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),{MAX_WIDTH},-2)'"
                    f":h='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),-2,{MAX_HEIGHT})',setsar=1{scaled_img_stream}"
                )
                overlay_filter = (
                    f"{video_label}{scaled_img_stream}"
                    f"overlay=x='{CENTER_X}-w/2':y='{CENTER_Y}-h/2':enable='between(t,{start},{end})'{out_label}"
                )
            vid_parts.extend([scale_filter, overlay_filter])
        video_label = out_label

    # 烧录字幕：叠加在全部视频滤镜之后（字幕永不被图片遮挡）
    if subtitle_filter:
        vid_parts.append(f"{video_label}{subtitle_filter}[vsub]")
        video_label = "[vsub]"

    has_filter = audio_filter_parts or vid_parts
    if has_filter:
        filter_parts = audio_filter_parts + vid_parts
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])

    # Video map
    if vid_parts:
        cmd.extend(["-map", video_label])
    else:
        cmd.extend(["-map", "0:v"])

    # Audio map
    cmd.extend(["-map", audio_map_label])
    cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", str(out_path)])
    run(cmd)


# ========== Assembler 主类 ==========

class FFmpegAssembler:
    def __init__(self, plan: PlanManifest, result: ResultManifest,
                 video_path: Path, output_path: Path,
                 bg_scale: float = 0.2, vol: float = 0.8,
                 fade: float = 2.0, trim_silence: bool = False, gain: float = None,
                 md_dir: Path = None, timeline_path: Path = None,
                 ken_burns_config=None, execution_assets: ExecutionAssets = None,
                 burn_subtitles: bool = False):
        self.plan = plan
        self.result = result
        self.video_path = video_path
        self.output_path = output_path
        self.bg_scale = bg_scale
        self.vol = vol
        self.fade = fade
        self.trim_silence = trim_silence
        self.gain = gain
        self.md_dir = Path(md_dir) if md_dir else Path.cwd()
        self.timeline_path = Path(timeline_path) if timeline_path else None
        self.ken_burns_config = ken_burns_config
        self.execution_assets = execution_assets
        self.burn_subtitles = burn_subtitles

    def assemble(self) -> Path:
        video_width, video_height = ffprobe_resolution(self.video_path)
        video_duration = ffprobe_duration(self.video_path)
        base_has_audio = has_audio_stream(self.video_path)
        print(f"Video: {video_width}x{video_height}, duration={video_duration:.2f}s")

        # 查找 timeline.json（manim 渲染时写入的实际视频时间）
        timeline_path = self.timeline_path
        print(f"Timeline: {timeline_path} (exists={timeline_path.exists() if timeline_path else False})")

        # 提取音乐/图片条目
        music_entries = extract_music_entries(self.plan, self.result, timeline_path)
        image_entries = extract_image_entries(self.plan, self.result, timeline_path)

        # 提取 per-shot 视觉产物（来自 Tool.execute() 输出）
        if self.execution_assets is not None:
            shot_visual_entries = extract_shot_visual_entries_from_assets(
                self.plan, self.execution_assets, self.result, timeline_path,
            )
        else:
            shot_visual_entries = extract_shot_visual_entries(self.result)
        image_entries = image_entries + shot_visual_entries

        print("Music entries:", music_entries)
        print("Image entries:", image_entries)

        # 判断 appendix 起始时间
        appendix_start = None
        for seg in self.plan.segments:
            if seg.segment_type == "appendix":
                # 找到第一个 appendix segment 的 result start time
                for rseg in self.result.segments:
                    if rseg.id == seg.id:
                        appendix_start = rseg.start
                        break
                break

        tmpdir = Path(tempfile.mkdtemp(prefix="md2vid_media_"))
        prepared_music, prepared_images = [], []
        try:
            for m in music_entries:
                name, src = m.get("name"), m.get("src")
                if not src:
                    continue
                src_path = (self.md_dir / src).resolve() if not Path(src).is_absolute() else Path(src)
                if not src_path.exists():
                    continue
                start = float(m["start"])
                end = m["end"] if m["end"] is not None else video_duration
                dur = max(0.0, end - start)
                if dur <= 0:
                    continue

                tmp_out = tmpdir / f"music_{music_entries.index(m)}.wav"
                prepare_audio_segment(src_path, dur, tmp_out,
                                      trim_silence=self.trim_silence, fade_in=self.fade)

                is_appendix = (appendix_start is not None and start >= appendix_start)
                vol = self.vol if is_appendix else max(0.0, self.vol * self.bg_scale)
                prepared_music.append({"path": tmp_out, "start": start, "volume": vol})

            for img in image_entries:
                src = img["src"]
                if not Path(src).is_absolute():
                    # 相对路径按 md_dir 解析；工具产物也可能相对 cwd，依次回退
                    candidates = [self.md_dir / src, Path.cwd() / src]
                    resolved = next(
                        (c.resolve() for c in candidates if c.exists()),
                        (self.md_dir / src).resolve(),
                    )
                    img["src"] = str(resolved)
                if Path(img["src"]).exists():
                    prepared_images.append(img)
                else:
                    print(f"  Image warning: src missing, overlay skipped: {img['src']}")

            # per-shot visual 按 scene 的 LayoutTemplate 摆放；无 layout 的条目保持旧行为
            attach_image_layout_regions(prepared_images, video_width, video_height)

            # 加载 Ken Burns 配置（若未在构造时传入）
            kb_config = self.ken_burns_config
            if kb_config is None:
                from md2video.config import load_ken_burns_config
                kb_config = load_ken_burns_config()

            # 烧录字幕：任何字幕问题都只降级（warning + 无字幕），不阻断成片
            subtitle_filter = None
            if self.burn_subtitles:
                try:
                    from md2video.assembler.subtitles import (
                        build_ass_file,
                        escape_filter_path,
                        extract_subtitle_entries,
                    )
                    entries = extract_subtitle_entries(
                        self.plan, timeline_path, self.execution_assets,
                    )
                    if entries:
                        ass_path = build_ass_file(
                            entries, video_width, video_height,
                            tmpdir / "subtitles.ass",
                        )
                        subtitle_filter = (
                            f"subtitles=filename='{escape_filter_path(ass_path)}'"
                        )
                        print(f"Subtitles: {len(entries)} entries")
                    else:
                        print("Subtitles: 0 narrated entries (skipped)")
                except Exception as exc:
                    print(f"  Subtitle warning (skipped): {exc}")

            build_and_run_ffmpeg(
                self.video_path, prepared_music, prepared_images,
                base_has_audio, self.output_path,
                video_duration, video_width, video_height, gain=self.gain,
                ken_burns_config=kb_config,
                subtitle_filter=subtitle_filter,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return self.output_path
