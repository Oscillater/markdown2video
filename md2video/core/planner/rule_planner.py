from __future__ import annotations

from typing import Any, List

from md2video.manifest.schema import ScenePlan, SegmentPlan, ShotPlan
from md2video.config import MAX_SCENE_CHARS


MARKER_SEGMENT_TYPES = frozenset({"marker_music", "marker_image"})
TITLE_SEGMENT_TYPES = frozenset({"title_main", "title_sub"})


def is_marker_segment(segment: SegmentPlan) -> bool:
    return segment.segment_type in MARKER_SEGMENT_TYPES


def renderable_segments(segments: List[SegmentPlan]) -> List[SegmentPlan]:
    return [segment for segment in segments if not is_marker_segment(segment)]


def marker_segment_to_cue(
    segment: SegmentPlan,
    *,
    position: str,
    anchor_segment_id: str = "",
) -> dict[str, Any]:
    marker_data = segment.marker_data or {}
    return {
        "id": segment.id,
        "cue_type": segment.segment_type,
        "kind": marker_data.get("kind", ""),
        "name": marker_data.get("name", ""),
        "position": position,
        "anchor_segment_id": anchor_segment_id,
        "section_context": segment.section_context,
    }


def attach_marker_cues_to_shots(
    source_segments: List[SegmentPlan],
    scenes: List[ScenePlan],
) -> List[ScenePlan]:
    """Attach source marker events to the nearest shot as cue metadata."""
    marker_segments = [segment for segment in source_segments if is_marker_segment(segment)]
    if not marker_segments:
        return scenes

    shot_by_segment_id: dict[str, ShotPlan] = {}
    for scene in scenes:
        for shot in scene.shots:
            for segment_id in shot.segment_ids:
                shot_by_segment_id[segment_id] = shot

    if not shot_by_segment_id:
        cues = [
            marker_segment_to_cue(segment, position="start")
            for segment in marker_segments
        ]
        return [
            ScenePlan(
                id="scene_001",
                shots=[ShotPlan(id="shot_001", cues=cues)],
            )
        ]

    previous_visible_id = ""
    for index, segment in enumerate(source_segments):
        if not is_marker_segment(segment):
            if segment.id in shot_by_segment_id:
                previous_visible_id = segment.id
            continue

        if previous_visible_id:
            shot = shot_by_segment_id[previous_visible_id]
            shot.cues.append(
                marker_segment_to_cue(
                    segment,
                    position="after",
                    anchor_segment_id=previous_visible_id,
                )
            )
            continue

        next_visible_id = ""
        for later_segment in source_segments[index + 1:]:
            if not is_marker_segment(later_segment) and later_segment.id in shot_by_segment_id:
                next_visible_id = later_segment.id
                break
        if next_visible_id:
            shot = shot_by_segment_id[next_visible_id]
            shot.cues.append(
                marker_segment_to_cue(
                    segment,
                    position="before",
                    anchor_segment_id=next_visible_id,
                )
            )

    return scenes


class RulePlanner:
    """Phase 2A 规则规划器: 将 segments 分组为 scenes（镜头）。"""

    # title 类型归为一组
    _TITLE_TYPES = TITLE_SEGMENT_TYPES

    def plan(self, segments: List[SegmentPlan]) -> List[ScenePlan]:
        scenes: List[ScenePlan] = []
        buf: List[SegmentPlan] = []  # 当前 scene 的 segments
        context = ""  # 当前 section_context
        char_count = 0  # 当前 scene content 累计字符数
        counter = 0  # scene 计数器
        shot_counter = 0  # shot 计数器

        def flush(visual_type="text_only", visual_params=None,
                  layout_type=None, layout_params=None):
            nonlocal counter, shot_counter, buf, char_count, context
            if not buf:
                return
            counter += 1
            shot_counter += 1
            scene_data = {
                "id": f"scene_{counter:03d}",
                "visual_type": visual_type,
                "visual_params": visual_params or {},
                "section_context": context,
                "shots": [ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[s.id for s in buf])],
            }
            if layout_type is not None:
                scene_data["layout_type"] = layout_type
            if layout_params is not None:
                scene_data["layout_params"] = layout_params
            scenes.append(ScenePlan(**scene_data))
            buf = []
            char_count = 0

        for seg in renderable_segments(segments):
            # R6: explicit segments 独立成 scene（visual/layout 决策在 scene 级，
            # v2 起 segment 不再携带 visual/layout 字段，走默认值）
            if seg.explicit:
                flush()
                counter += 1
                shot_counter += 1
                scenes.append(ScenePlan(
                    id=f"scene_{counter:03d}",
                    section_context=seg.section_context,
                    shots=[ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[seg.id])],
                ))
                continue

            # R1: title 类型归入同一 scene
            if seg.segment_type in self._TITLE_TYPES:
                buf.append(seg)
                continue

            # R3: section_header 开启新 scene
            if seg.segment_type == "section_header":
                flush()
                context = seg.section_context or seg.text
                buf.append(seg)
                char_count += len(seg.text)
                continue

            # R4 + R5: content/appendix 归入当前 scene，超长时拆分
            if char_count + len(seg.text) > MAX_SCENE_CHARS and buf:
                flush()
                # 保持 section_context
                context = context or seg.section_context

            buf.append(seg)
            context = seg.section_context or context
            char_count += len(seg.text)

        flush()
        return attach_marker_cues_to_shots(segments, scenes)
