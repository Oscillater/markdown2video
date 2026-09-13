"""烧录字幕（知识区格式 P0）：timeline text cue → ASS → libass 逐段叠加。

字幕的定位是**文字的唯一载体**（知识区格式：画面 + 字幕 + 解说）。白名单
与 bundle SRT 导出一致：只上 content / appendix（标题卡与 section header
有自己的屏上位置，不走字幕）。更关键的一刀：只有**真的被朗读的段**才上字
幕——朗读事实优先取 execution-assets 的音频资产（音频按 segment_id 绑定，
不依赖列表顺序），资产缺位时回退到 plan 的 audio_request 判定。

ASS 而非逐段 drawtext：libass 处理中文/换行/样式，文本零转义（花括号
消毒即可），一条 subtitles 滤镜叠加在全部视频滤镜之后（字幕永不被盖）。
构建是纯函数、逐字节确定；任何字幕问题都不许阻断成片（调用方降级）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# 与 bundle SRT 白名单一致：挂屏文本（标题/header）不进字幕轨
SUBTITLE_SEGMENT_TYPES = ("content", "appendix")

# v1 从简：底边居中、白字黑边；样式接管归 knowledge pack
DEFAULT_FONT_NAME = "Microsoft YaHei"
DEFAULT_FONT_SIZE_RATIO = 0.045
DEFAULT_MARGIN_V_RATIO = 0.06
DEFAULT_OUTLINE_PX = 2


def extract_subtitle_entries(
    plan,
    timeline_path: Path | None,
    execution_assets=None,
) -> List[Dict[str, Any]]:
    """timeline text facts → 字幕条目（只留被朗读的 content/appendix）。

    朗读事实：execution_assets 的音频资产优先（segment_id 绑定），缺位时
    回退 plan 的 audio_request 判定。timeline 缺失/无 text 返回空表。
    """
    if not timeline_path or not Path(timeline_path).exists():
        return []
    data = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    text_facts = data.get("text", [])

    narrated_ids = _narrated_segment_ids(plan, execution_assets)

    entries: List[Dict[str, Any]] = []
    for fact in text_facts:
        if fact.get("segment_type") not in SUBTITLE_SEGMENT_TYPES:
            continue
        segment_id = fact.get("segment_id", "")
        if segment_id not in narrated_ids:
            continue
        text = str(fact.get("text", "")).strip()
        if not text:
            continue
        entries.append({
            "segment_id": segment_id,
            "text": text,
            "start": float(fact["start"]),
            "end": float(fact["end"]),
        })
    entries.sort(key=lambda e: e["start"])
    return entries


def _narrated_segment_ids(plan, execution_assets) -> set[str]:
    if execution_assets is not None:
        return {
            asset.segment_id
            for asset in execution_assets.audio_assets
            if asset.path and asset.duration > 0
        }
    return {
        segment.id
        for segment in plan.segments
        if segment.audio_request is not None
        and segment.segment_type in SUBTITLE_SEGMENT_TYPES
    }


def _ass_time(seconds: float) -> str:
    """ASS 时码 H:MM:SS.CC（厘秒）。"""
    total = max(0.0, float(seconds))
    centis = int(round(total * 100))
    hours, rem = divmod(centis, 3600 * 100)
    minutes, rem = divmod(rem, 60 * 100)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _sanitize_text(text: str) -> str:
    """ASS 文本消毒：花括号是 override 标签语法，必须换成普通括号。"""
    return str(text).replace("{", "(").replace("}", ")").replace("\n", " ")


def _wrap_cjk_text(
    text: str,
    video_width: int,
    font_size: int,
    side_margin: int = 40,
) -> str:
    """按像素宽度预换行（行间用 ASS 的 \\N）。

    实测当前 libass 构建（0.17.4, directwrite provider）对无空格中文长句
    **不做断行**、直接水平裁边——不能指望渲染端 WrapStyle。这里按
    （画宽 − 两侧边距）/ 字号 估算每行字数手动折行；ASCII 字符实际更窄，
    按全角宽估算偏保守（行更短），安全方向。行首避标点：折行落在标点上
    时把标点挪到上一行尾。
    """
    usable = max(80, video_width - 2 * side_margin)
    per_line = max(4, int(usable // max(1, font_size)))
    sanitized = _sanitize_text(text)
    if len(sanitized) <= per_line:
        return sanitized

    closing = set("，。、；：？！）】》\"'…")
    chunks = [sanitized[i:i + per_line] for i in range(0, len(sanitized), per_line)]
    for index in range(1, len(chunks)):
        while chunks[index] and chunks[index][0] in closing:
            chunks[index - 1] += chunks[index][0]
            chunks[index] = chunks[index][1:]
    return "\\N".join(chunk for chunk in chunks if chunk)


def build_ass_file(
    entries: List[Dict[str, Any]],
    video_width: int,
    video_height: int,
    out_path: Path,
    font_name: str = DEFAULT_FONT_NAME,
    font_size_ratio: float = DEFAULT_FONT_SIZE_RATIO,
    margin_v_ratio: float = DEFAULT_MARGIN_V_RATIO,
    outline_px: int = DEFAULT_OUTLINE_PX,
) -> Path:
    """字幕条目 → ASS 文件（逐字节确定）。"""
    font_size = max(12, round(video_height * font_size_ratio))
    margin_v = max(8, round(video_height * margin_v_ratio))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00101010,&H96000000,0,0,0,0,100,100,0,0,1,{outline_px},1,"
        f"2,40,40,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )
    lines = [header]
    for entry in entries:
        wrapped = _wrap_cjk_text(
            entry["text"], video_width, font_size, side_margin=40,
        )
        lines.append(
            f"Dialogue: 0,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
            f"Sub,,0,0,0,,{wrapped}\n"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def escape_filter_path(path: Path | str) -> str:
    """文件路径 → ffmpeg 滤镜参数安全写法（Windows 盘符冒号是主要雷区）。"""
    text = str(path).replace("\\", "/").replace("'", "\\'")
    return text.replace(":", "\\:")
