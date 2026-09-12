"""Remotion 后端的纯函数调度器（A6 后半）。

时间裁决与 Manim 渲染器同语义：音频事实 > hold cue（未来入口）> pack
静默节奏（title_hold / section_header / body）。plan 不含时间，本模块从
ExecutionAssets 的音频事实 + 设计包节奏推导出确定性调度（渲染前算好），
作为 props 交给 Node 侧 composition 逐帧执行，并产出与 manim 后端同构的
timeline 事实（text / markers / shots），供同一道时间不变量闸门校验。

与 manim 渲染器的已记录差异：

- 动效不消耗时间窗口：manim 的 Write/FadeIn run_time 会推进 self.time，
  这里动效一律在可见窗口内完成，时间线只描述可见窗口本身。
- 换行交给 CSS 宽度约束，不使用 manim 的 MAX_CHARS_PER_LINE 硬换行。
- section header 的堆叠字幕闭合时机取近似：被下一个 header 顶掉时闭合，
  否则视频结束时闭合（manim 在堆叠溢出 FIFO 移除时闭合）。
- 标题卡片与标题 cue 全程可见（manim 中标题 mobject 同样存留到片尾）。

纯函数：plan + assets + pack 进，schedule dict 出；不做 I/O、不依赖 Node。
"""
from __future__ import annotations

from typing import Any

from md2video.config import MANIM_FRAME_RATE, MANIM_HEIGHT, MANIM_WIDTH
from md2video.layout.mapping import box_pixel_rect
from md2video.manifest.schema import ExecutionAssets, PlanManifest
from md2video.style.schema import ThemeTokens
from md2video.tools.render.manim_renderer_inputs import (
    TITLE_SEGMENT_TYPES,
    ShotRenderUnit,
    compute_shot_layout,
    iter_shot_render_units,
    segment_uses_voiceover,
)

# Remotion v1 与 manim 共用渲染契约画布（480x854 @30fps，manim.cfg 声明）；
# 后端自声明画布属于未来能力合同。
REMOTION_WIDTH = MANIM_WIDTH
REMOTION_HEIGHT = MANIM_HEIGHT
REMOTION_FPS = MANIM_FRAME_RATE

# 引擎能力词汇声明（架构：引擎声明自己支持哪些名字，不认识的降级 + warning）
REVEAL_CAPABILITIES = ("write", "fade", "appear")
DISMISS_CAPABILITIES = ("instant", "fade")
MOTIF_KIND_CAPABILITIES = ("orbit_dots",)

SCHEDULE_VERSION = "remotion.v1"

_SILENT_SLOT_BY_TYPE = {
    "section_header": "section_header",
}
_DEFAULT_SILENT_SLOT = "body"


def _audio_facts(assets: ExecutionAssets) -> dict[str, tuple[str, float]]:
    """segment_id -> (audio path, duration)；只收带路径的正时长事实。"""
    facts: dict[str, tuple[str, float]] = {}
    for asset in assets.audio_assets:
        if asset.path and asset.duration > 0:
            facts[asset.segment_id] = (asset.path, float(asset.duration))
    return facts


def find_title_unit(
    units: list[ShotRenderUnit],
) -> tuple[ShotRenderUnit | None, Any, Any]:
    """镜像 ManimRenderer._find_title_unit：首个含 title segment 的 unit。"""
    for unit in units:
        title_main = None
        title_sub = None
        for render_segment in unit.segments:
            seg = render_segment.segment
            if seg.segment_type == "title_main" and title_main is None:
                title_main = seg
            elif seg.segment_type == "title_sub" and title_sub is None:
                title_sub = seg
        if title_main is not None or title_sub is not None:
            return unit, title_main, title_sub
    return None, None, None


def _region_payload(
    unit: ShotRenderUnit, width: int, height: int
) -> dict[str, Any]:
    """layout 契约 → 像素矩形（top-left origin），交给 CSS 绝对定位。"""
    computed = compute_shot_layout(
        unit, frame_width_px=width, frame_height_px=height
    )
    return {
        "regions": {
            name: box_pixel_rect(box, width, height)
            for name, box in computed.regions.items()
        },
        "has_image_region": "image" in computed.regions,
    }


def style_payload(pack: ThemeTokens) -> tuple[dict[str, Any], list[str]]:
    """ThemeTokens → Node 侧 style payload；能力词汇外的意图降级 + warning。"""
    warnings: list[str] = []

    def reveal(intent: str) -> str:
        if intent in REVEAL_CAPABILITIES:
            return intent
        warnings.append(
            f"Unknown reveal intent {intent!r}; degrading to 'appear' "
            "(pack/engine capability mismatch)"
        )
        return "appear"

    def dismiss(intent: str) -> str:
        if intent in DISMISS_CAPABILITIES:
            return intent
        warnings.append(
            f"Unknown dismiss intent {intent!r}; degrading to 'instant' "
            "(pack/engine capability mismatch)"
        )
        return "instant"

    motif_kind = pack.motif.kind
    if motif_kind and motif_kind not in MOTIF_KIND_CAPABILITIES:
        warnings.append(
            f"Unknown motif kind {motif_kind!r}; degrading to no motif "
            "(pack/engine capability mismatch)"
        )
        motif_kind = ""

    typography = pack.typography
    style = {
        "id": pack.id,
        "palette": pack.palette.model_dump(),
        "typography": {
            "font_family": typography.font_family,
            "sizes_px": {
                "title_main": max(1, round(typography.size_title_main * REMOTION_HEIGHT)),
                "title_sub": max(1, round(typography.size_title_sub * REMOTION_HEIGHT)),
                "section_header": max(
                    1, round(typography.size_section_header * REMOTION_HEIGHT)
                ),
                "section_header_detail": max(
                    1, round(typography.size_section_header_detail * REMOTION_HEIGHT)
                ),
                "body": max(1, round(typography.size_body * REMOTION_HEIGHT)),
            },
        },
        "motion": {
            "title_reveal": reveal(pack.motion.title_reveal),
            "section_reveal": reveal(pack.motion.section_reveal),
            "body_reveal": reveal(pack.motion.body_reveal),
            "body_dismiss": dismiss(pack.motion.body_dismiss),
            "section_dismiss": dismiss(pack.motion.section_dismiss),
            "motif_transition_duration": pack.motion.motif_transition_duration,
        },
        "motif": {"kind": motif_kind},
    }
    return style, warnings


def build_remotion_schedule(
    plan: PlanManifest,
    assets: ExecutionAssets,
    pack: ThemeTokens,
    *,
    width: int = REMOTION_WIDTH,
    height: int = REMOTION_HEIGHT,
    fps: int = REMOTION_FPS,
) -> tuple[dict[str, Any], list[str]]:
    """推导确定性调度（同 manim construct 时序语义），返回 (schedule, warnings)。"""
    style, warnings = style_payload(pack)
    scene_components, component_warnings = _scene_component_payloads(plan)
    warnings.extend(component_warnings)
    audio_by_segment = _audio_facts(assets)

    units_all = list(iter_shot_render_units(plan, include_title_segments=True))
    units_body = list(iter_shot_render_units(plan))
    full_ids_by_shot: dict[str, list[str]] = {}
    full_units_by_shot: dict[str, ShotRenderUnit] = {}
    for unit in units_all:
        full_ids_by_shot.setdefault(unit.shot_id, unit.segment_ids)
        full_units_by_shot.setdefault(unit.shot_id, unit)

    # timeline text facts（start/end = 可见窗口；end 在闭合时回填）
    text_facts: list[dict[str, Any]] = []
    markers_out: list[dict[str, Any]] = []
    shots_by_id: dict[str, dict[str, Any]] = {}
    # 可见窗口载荷（composition 消费；title/section header 全程可见语义）
    open_window_cues: dict[str, tuple[int, str]] = {}
    pending_after_cues: list[dict[str, Any]] = []
    time = 0.0

    def upsert_shot(
        unit: ShotRenderUnit, start: float, end: float
    ) -> dict[str, Any]:
        entry = shots_by_id.get(unit.shot_id)
        if entry is None:
            payload = _region_payload(full_units_by_shot[unit.shot_id], width, height)
            entry = {
                "shot_id": unit.shot_id,
                "scene_id": unit.scene_id,
                "segment_ids": list(full_ids_by_shot.get(unit.shot_id, [])),
                "layout_type": unit.layout_type,
                "start": start,
                "end": end,
                "regions": payload["regions"],
                "has_image_region": payload["has_image_region"],
                "segments": [],
            }
            # A8：scene 声明了已注册的表现组件时随 payload 下发（Node 侧按
            # ref 查组件，查不到走引擎默认渲染）；字段缺省 = 无组件，不改动
            # 无组件 run 的既有 props。
            component_ref = scene_components.get(unit.scene_id, "")
            if component_ref:
                entry["component"] = component_ref
            shots_by_id[unit.shot_id] = entry
            return entry
        entry["start"] = min(entry["start"], start)
        entry["end"] = max(entry["end"], end)
        return entry

    def append_text_fact(
        seg, start: float, end: float | None, unit: ShotRenderUnit | None
    ) -> int:
        location = (
            {"scene_id": unit.scene_id, "shot_id": unit.shot_id}
            if unit is not None
            else {"scene_id": "", "shot_id": ""}
        )
        text_facts.append({
            "segment_id": seg.id,
            "segment_type": seg.segment_type,
            "text": seg.text,
            "start": start,
            "end": end,
            **location,
        })
        return len(text_facts) - 1

    # ---- 标题 pass（镜像 _construct_by_scenes：标题最先渲染）----
    title_unit, title_main, title_sub = find_title_unit(units_all)
    title_payload: dict[str, Any] | None = None
    title_segments: list[dict[str, Any]] = []
    title_regions: dict[str, Any] = {}
    body_pending_start: dict[str, float] = {}
    if title_main is not None or title_sub is not None:
        title_start = time
        if title_unit is not None:
            title_regions = _region_payload(title_unit, width, height)
        for seg in (title_main, title_sub):
            if seg is None:
                continue
            index = append_text_fact(seg, title_start, None, title_unit)
            open_window_cues[seg.id] = (index, "title")
            title_segments.append({
                "segment_id": seg.id,
                "segment_type": seg.segment_type,
                "text": seg.text,
                "start": title_start,
                "end": None,
                "audio_path": "",
                "shot_id": title_unit.shot_id if title_unit is not None else "",
                "scene_id": title_unit.scene_id if title_unit is not None else "",
            })
        time += pack.motion.silent.title_hold
        if title_unit is not None and all(
            item.segment.segment_type in TITLE_SEGMENT_TYPES
            for item in title_unit.segments
        ):
            upsert_shot(title_unit, title_start, time)
        elif title_unit is not None:
            # 标题 shot 还有正文：shot 从标题起点开始，正文在同一 shot 内继续
            body_pending_start = {title_unit.shot_id: title_start}

    # ---- 正文 pass（按 scene/shot 顺序）----
    for unit in units_body:
        shot_start = body_pending_start.pop(unit.shot_id, time)

        for cue in unit.cues:
            if cue.get("position", "start") != "start":
                continue
            markers_out.append(_marker_entry(cue, shot_start, unit))

        shot_entry = shots_by_id.get(unit.shot_id)
        if shot_entry is None:
            shot_entry = upsert_shot(unit, shot_start, shot_start)
        else:
            shot_entry["start"] = min(shot_entry["start"], shot_start)

        for render_segment in unit.segments:
            seg = render_segment.segment
            for cue in unit.cues:
                position = cue.get("position", "start")
                if position not in ("before", "after"):
                    continue
                if cue.get("anchor_segment_id", "") != seg.id:
                    continue
                entry = _marker_entry(cue, None, unit, anchor=seg.id, position=position)
                pending_after_cues.append(entry)
                if position == "before":
                    entry["time"] = time
                    markers_out.append(_public_marker(entry))

            seg_start = time
            if segment_uses_voiceover(seg):
                fact = audio_by_segment.get(seg.id)
                duration = fact[1] if fact else 0.0
                audio_path = fact[0] if fact else ""
            else:
                slot = _SILENT_SLOT_BY_TYPE.get(seg.segment_type, _DEFAULT_SILENT_SLOT)
                duration = getattr(pack.motion.silent, slot)
                audio_path = ""
            time += duration
            seg_end = time

            if seg.segment_type == "section_header":
                # 新 header 顶掉旧堆叠 cue（近似 manim 的堆叠替换）
                for cue_id, (index, kind) in list(open_window_cues.items()):
                    if kind == "section" and text_facts[index]["end"] is None:
                        text_facts[index]["end"] = seg_start
                        del open_window_cues[cue_id]
                index = append_text_fact(seg, seg_start, None, unit)
                open_window_cues[seg.id] = (index, "section")
            else:
                append_text_fact(seg, seg_start, seg_end, unit)

            shot_entry["segments"].append({
                "segment_id": seg.id,
                "segment_type": seg.segment_type,
                "text": seg.text,
                "start": seg_start,
                "end": seg_end,
                "audio_path": audio_path,
                "shot_id": unit.shot_id,
                "scene_id": unit.scene_id,
            })

            for marker in pending_after_cues:
                if marker.get("_anchor") == seg.id and marker.get("_position") == "after":
                    marker["time"] = seg_end
                    markers_out.append(_public_marker(marker))
            pending_after_cues = [
                m for m in pending_after_cues if m.get("time") is None
            ]

        for cue in unit.cues:
            if cue.get("position", "start") != "end":
                continue
            markers_out.append(_marker_entry(cue, time, unit))

        # 锚点段不在本 shot 段列表（如锚在标题段）的 before/after cue：
        # 在本 shot 末端收敛，防止漂到全片末端撞碎区间约束。
        unit_segment_ids = {rs.segment.id for rs in unit.segments}
        for cue in unit.cues:
            if cue.get("position", "start") not in ("before", "after"):
                continue
            if cue.get("anchor_segment_id", "") in unit_segment_ids:
                continue
            markers_out.append(_public_marker(_marker_entry(cue, time, unit)))

        for marker in pending_after_cues:
            if marker.get("time") is None and marker.get("shot_id") == unit.shot_id:
                marker["time"] = time
                markers_out.append(_public_marker(marker))
        pending_after_cues = [
            m for m in pending_after_cues if m.get("time") is None
        ]

        shot_entry["end"] = max(shot_entry["end"], time)

    # ---- finish：未闭合 cue 到视频末尾（镜像 _finish）----
    total = time
    for cue_id, (index, _kind) in open_window_cues.items():
        text_facts[index]["end"] = total
    for segment in title_segments:
        segment["end"] = total
    for marker in pending_after_cues:
        if marker.get("time") is None:
            # 锚点段没进正文 pass（如锚在标题区）：挂回 cue 所属 shot 末端，
            # 既保住闸门的 shot 区间约束，也不吃任何时间窗口。
            shot_entry = shots_by_id.get(marker.get("shot_id", ""))
            marker["time"] = shot_entry["end"] if shot_entry else total
        markers_out.append(_public_marker(marker))

    if title_segments:
        title_payload = {
            "layout_type": title_unit.layout_type if title_unit is not None else "",
            "regions": title_regions.get("regions", {}),
            "has_image_region": title_regions.get("has_image_region", False),
            "segments": title_segments,
        }

    shots_out = [shots_by_id[unit.shot_id] for unit in units_all if unit.shot_id in shots_by_id]
    timeline_facts = {
        "fps": fps,
        "text": text_facts,
        "markers": markers_out,
        "shots": [
            {
                "shot_id": shot["shot_id"],
                "scene_id": shot["scene_id"],
                "segment_ids": shot["segment_ids"],
                "layout_type": shot["layout_type"],
                "start": shot["start"],
                "end": shot["end"],
            }
            for shot in shots_out
        ],
    }

    schedule = {
        "version": SCHEDULE_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "duration": total,
        "style": style,
        "title": title_payload,
        "shots": shots_out,
        "timeline": timeline_facts,
    }
    return schedule, warnings


def _scene_component_payloads(plan: PlanManifest) -> tuple[dict[str, str], list[str]]:
    """scene_id -> 组件 ref（A8）。未注册 / 已注册但未安装进 Remotion 工程
    的组件都在这里降级 + warning：调度 payload 不带 component 字段，Node
    侧走引擎默认渲染（与 pack 未知名同通道，不做静默降级）。"""
    from md2video.components.registry import get_component, is_installed

    refs: dict[str, str] = {}
    warnings: list[str] = []
    for scene in plan.scenes:
        if not scene.component:
            continue
        if get_component(scene.component) is None:
            warnings.append(
                f"Component {scene.component!r} is not registered "
                f"(scene {scene.id}); falling back to engine default rendering"
            )
            continue
        if not is_installed(scene.component):
            warnings.append(
                f"Component {scene.component!r} is registered but not installed "
                f"into the Remotion backend (scene {scene.id}); falling back to "
                "engine default rendering"
            )
            continue
        refs[scene.id] = scene.component
    return refs, warnings


def _public_marker(entry: dict[str, Any]) -> dict[str, Any]:
    """剥掉 `_` 前缀调度簿记键，落盘的 timeline 与 manim 后端同构。"""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def _marker_entry(
    cue: dict[str, Any],
    time_value: float | None,
    unit: ShotRenderUnit,
    *,
    anchor: str = "",
    position: str = "",
) -> dict[str, Any]:
    entry = {
        "id": cue.get("id", ""),
        "cue_type": cue.get("cue_type", ""),
        "kind": cue.get("kind", ""),
        "name": cue.get("name", ""),
        "time": time_value,
        "scene_id": unit.scene_id,
        "shot_id": unit.shot_id,
    }
    if anchor:
        entry["_anchor"] = anchor
        entry["_position"] = position
    return entry
