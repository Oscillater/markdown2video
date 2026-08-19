from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from .segmenter import custom_sentence_split


# ========== 声明/标记解析 ==========

def _parse_music_declaration(line: str) -> Optional[Tuple[str, str]]:
    line = line.strip()
    m = re.match(r'^\[music:\s*(.+)\]\s*$', line, re.IGNORECASE)
    body = None
    if m:
        body = m.group(1)
    else:
        m2 = re.match(r'^(?:music|音乐)\s*[:：]\s*(.+)$', line, re.IGNORECASE)
        if m2:
            body = m2.group(1)
    if not body:
        return None
    return _extract_name_src(body)


def _parse_music_marker(line: str) -> Optional[Tuple[str, str]]:
    s = line.strip()
    m = re.match(r'^[\[\<]\s*music_(start|end)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\]\>]+))[\]\>]\s*$', s, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or m.group(3) or m.group(4)).strip()


def _parse_image_declaration(line: str) -> Optional[Tuple[str, str]]:
    line = line.strip()
    m = re.match(r'^\[image:\s*(.+)\]\s*$', line, re.IGNORECASE)
    body = None
    if m:
        body = m.group(1)
    else:
        m2 = re.match(r'^(?:image|图片)\s*[:：]\s*(.+)$', line, re.IGNORECASE)
        if m2:
            body = m2.group(1)
    if not body:
        return None
    return _extract_name_src(body)


def _parse_image_marker(line: str) -> Optional[Tuple[str, str]]:
    s = line.strip()
    m = re.match(r'^[\[\<]\s*image_(start|end)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\]\>]+))[\]\>]\s*$', s, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or m.group(3) or m.group(4)).strip()


def _extract_name_src(body: str) -> Optional[Tuple[str, str]]:
    name, src = None, None
    for part in re.split(r'\s*,\s*', body):
        kv = re.match(r'^\s*name\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv:
            name = (kv.group(1) or kv.group(2) or kv.group(3)).strip()
            continue
        kv2 = re.match(r'^\s*src\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv2:
            src = (kv2.group(1) or kv2.group(2) or kv2.group(3)).strip()
    if name and src:
        return name, src
    return None


# ========== 内部解析 (与原始 parse_markdown_sections 等价) ==========

def _parse_markdown_sections(text: str) -> dict:
    lines = text.splitlines()
    sections = {
        "h1": None, "h2": None,
        "contents": [], "appendix": [],
        "music": {}, "images": {},
    }

    # 顶部声明区
    idx = 0
    while idx < len(lines):
        raw = lines[idx].strip()
        if not raw:
            idx += 1
            continue
        parsed_m = _parse_music_declaration(raw)
        parsed_i = _parse_image_declaration(raw)
        if parsed_m:
            name, src = parsed_m
            sections["music"][name] = src
            lines[idx] = ""
            idx += 1
            continue
        if parsed_i:
            name, src = parsed_i
            sections["images"][name] = src
            lines[idx] = ""
            idx += 1
            continue
        break

    current_h3, current_text_block, is_appendix = None, [], False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _parse_music_marker(stripped) or _parse_image_marker(stripped):
            (sections["appendix"] if is_appendix else current_text_block).append(stripped)
            continue
        if stripped.startswith("# "):
            sections["h1"] = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections["h2"] = stripped[3:].strip()
        elif stripped.startswith("### "):
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(p) for p in current_text_block]
                })
            current_h3, current_text_block = stripped[4:].strip(), []
        elif stripped == "---":
            is_appendix = True
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(p) for p in current_text_block]
                })
                current_h3, current_text_block = None, []
        else:
            (sections["appendix"] if is_appendix else current_text_block).append(stripped)

    if current_h3 and current_text_block:
        sections["contents"].append({
            "h3": current_h3,
            "text": [custom_sentence_split(p) for p in current_text_block]
        })

    return sections


# ========== Plan Manifest 生成 ==========

def parse_to_plan_manifest(md_path: str) -> "PlanManifest":
    """解析 Markdown 文件，输出 PlanManifest。"""
    from md2video.manifest.schema import PlanManifest, SegmentPlan, AudioRequest

    path = Path(md_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {md_path}")
    text = path.read_text(encoding="utf-8")
    sections = _parse_markdown_sections(text)

    segments = []
    seg_counter = 0

    def next_id() -> str:
        nonlocal seg_counter
        seg_counter += 1
        return f"seg_{seg_counter:03d}"

    # 标题
    if sections["h1"]:
        segments.append(SegmentPlan(
            id=next_id(), text=sections["h1"],
            segment_type="title_main",
        ))
    if sections["h2"]:
        segments.append(SegmentPlan(
            id=next_id(), text=sections["h2"],
            segment_type="title_sub",
        ))

    # 内容区
    for content in sections["contents"]:
        h3 = content.get("h3", "")
        if h3:
            segments.append(SegmentPlan(
                id=next_id(), text=h3,
                segment_type="section_header", audio_request=AudioRequest(),
                section_context=h3,
            ))
        for para in content.get("text", []):
            for sentence in para:
                # 检查是否为 marker
                mm = _parse_music_marker(sentence)
                if mm:
                    segments.append(SegmentPlan(
                        id=next_id(), text=sentence,
                        segment_type="marker_music",
                        marker_data={"kind": mm[0], "name": mm[1]},
                        section_context=h3,
                    ))
                    continue
                im = _parse_image_marker(sentence)
                if im:
                    segments.append(SegmentPlan(
                        id=next_id(), text=sentence,
                        segment_type="marker_image",
                        marker_data={"kind": im[0], "name": im[1]},
                        section_context=h3,
                    ))
                    continue
                segments.append(SegmentPlan(
                    id=next_id(), text=sentence,
                    segment_type="content", audio_request=AudioRequest(),
                    section_context=h3,
                ))

    # 附录
    for line in sections.get("appendix", []):
        mm = _parse_music_marker(line)
        if mm:
            segments.append(SegmentPlan(
                id=next_id(), text=line,
                segment_type="marker_music",
                marker_data={"kind": mm[0], "name": mm[1]},
            ))
            continue
        im = _parse_image_marker(line)
        if im:
            segments.append(SegmentPlan(
                id=next_id(), text=line,
                segment_type="marker_image",
                marker_data={"kind": im[0], "name": im[1]},
            ))
            continue
        for sentence in custom_sentence_split(line):
            segments.append(SegmentPlan(
                id=next_id(), text=sentence,
                segment_type="appendix", audio_request=AudioRequest(),
            ))

    media_declarations = {}
    if sections["music"]:
        media_declarations["music"] = sections["music"]
    if sections["images"]:
        media_declarations["images"] = sections["images"]

    return PlanManifest(
        version="1",
        segments=segments,
        media_declarations=media_declarations,
    )
