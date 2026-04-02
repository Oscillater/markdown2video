from __future__ import annotations

from typing import List

from md2video.manifest.schema import ScenePlan, SegmentPlan, ShotPlan
from md2video.config import MAX_SCENE_CHARS


class RulePlanner:
    """Phase 2A 规则规划器: 将 segments 分组为 scenes（镜头）。"""

    # marker 类型不参与内容分组
    _MARKER_TYPES = frozenset({"marker_music", "marker_image"})
    # title 类型归为一组
    _TITLE_TYPES = frozenset({"title_main", "title_sub"})

    def plan(self, segments: List[SegmentPlan]) -> List[ScenePlan]:
        scenes: List[ScenePlan] = []
        buf: List[SegmentPlan] = []  # 当前 scene 的 segments
        context = ""  # 当前 section_context
        char_count = 0  # 当前 scene content 累计字符数
        counter = 0  # scene 计数器
        shot_counter = 0  # shot 计数器

        def flush(visual_type="text_only", visual_params=None):
            nonlocal counter, shot_counter, buf, char_count, context
            if not buf:
                return
            counter += 1
            shot_counter += 1
            scenes.append(ScenePlan(
                id=f"scene_{counter:03d}",
                visual_type=visual_type,
                visual_params=visual_params or {},
                section_context=context,
                shots=[ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[s.id for s in buf])],
            ))
            buf = []
            char_count = 0

        for seg in segments:
            # R2: markers 独立成 singleton scene
            if seg.segment_type in self._MARKER_TYPES:
                flush()
                counter += 1
                shot_counter += 1
                scenes.append(ScenePlan(
                    id=f"scene_{counter:03d}",
                    section_context=seg.section_context,
                    shots=[ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[seg.id])],
                ))
                continue

            # R6: explicit segments 独立成 scene
            if seg.explicit:
                flush()
                counter += 1
                shot_counter += 1
                scenes.append(ScenePlan(
                    id=f"scene_{counter:03d}",
                    visual_type=seg.visual_type,
                    visual_params=seg.visual_params,
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
        return scenes


def denormalize_scenes_to_segments(
    segments: List[SegmentPlan], scenes: List[ScenePlan]
) -> None:
    """将 scene 的 visual_type/visual_params 复制到其包含的 non-explicit segments 上。"""
    scene_map: dict[str, ScenePlan] = {}
    for scene in scenes:
        for shot in scene.shots:
            for seg_id in shot.segment_ids:
                scene_map[seg_id] = scene

    for seg in segments:
        if seg.explicit:
            continue
        scene = scene_map.get(seg.id)
        if scene:
            seg.visual_type = scene.visual_type
            seg.visual_params = scene.visual_params
