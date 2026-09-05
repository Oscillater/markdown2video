"""Pure input helpers for the Manim renderer."""
from __future__ import annotations

from typing import Any, Iterable, NamedTuple

from md2video.config import RENDER_BACKEND_ONLY_VISUAL_TYPES
from md2video.core.planner.rule_planner import MARKER_SEGMENT_TYPES
from md2video.manifest.schema import (
    ExecutionAssets,
    PlanManifest,
    SegmentPlan,
    SegmentResult,
)


TITLE_SEGMENT_TYPES = {"title_main", "title_sub"}
TIMED_SEGMENT_TYPES = {"section_header", "content", "appendix"}


class TitleLayoutPart(NamedTuple):
    segment: SegmentPlan
    font_size: int
    position: tuple[float, float, float]


class RenderSegment(NamedTuple):
    segment: SegmentPlan
    target_duration: float


class ShotRenderUnit(NamedTuple):
    scene_id: str
    shot_id: str
    segments: tuple[RenderSegment, ...]
    cues: tuple[dict[str, Any], ...]
    layout_type: str
    layout_params: dict[str, Any]

    @property
    def segment_ids(self) -> list[str]:
        return [item.segment.id for item in self.segments]


def title_layout_parts(
    title_main: SegmentPlan | None,
    title_sub: SegmentPlan | None,
) -> list[TitleLayoutPart]:
    """Return title card layout parts without importing Manim."""
    if title_main and title_sub:
        return [
            TitleLayoutPart(title_main, 40, (0.0, 1.0, 0.0)),
            TitleLayoutPart(title_sub, 30, (0.0, -1.0, 0.0)),
        ]
    if title_main:
        return [TitleLayoutPart(title_main, 40, (0.0, 0.0, 0.0))]
    if title_sub:
        return [TitleLayoutPart(title_sub, 30, (0.0, 0.0, 0.0))]
    return []


def segment_consumes_timeline_duration(segment: SegmentPlan) -> bool:
    """Return whether a segment should consume shot time in the body pass."""
    return segment.segment_type in TIMED_SEGMENT_TYPES


def iter_shot_render_units(
    plan: PlanManifest,
    *,
    include_title_segments: bool = False,
) -> Iterable[ShotRenderUnit]:
    """Yield renderer execution units in scene/shot order.

    Each unit carries the shot and scene contracts that the Manim renderer needs
    without importing Manim or computing pixel layout.
    """
    segment_by_id = {segment.id: segment for segment in plan.segments}

    if not plan.scenes:
        raise ValueError("Renderer input requires scene/shot structure")

    for scene in plan.scenes:
        for shot in scene.shots:
            render_segments: list[RenderSegment] = []
            for segment_id in shot.segment_ids:
                segment = segment_by_id.get(segment_id)
                if segment is None:
                    raise ValueError(
                        "Renderer input references unknown segment_id "
                        f"in scene {scene.id}, shot {shot.id}: {segment_id}"
                    )
                if segment.segment_type in MARKER_SEGMENT_TYPES:
                    raise ValueError(
                        "Renderer input references marker segment as renderable "
                        f"in scene {scene.id}, shot {shot.id}: {segment_id}"
                    )
                if not include_title_segments and segment.segment_type in TITLE_SEGMENT_TYPES:
                    continue
                render_segments.append(RenderSegment(segment, segment.target_duration))

            if not render_segments and not shot.cues:
                continue
            yield ShotRenderUnit(
                scene_id=scene.id,
                shot_id=shot.id,
                segments=tuple(render_segments),
                cues=tuple(dict(cue) for cue in shot.cues),
                layout_type=scene.layout_type,
                layout_params=dict(scene.layout_params),
            )


def iter_scene_render_segments(plan: PlanManifest) -> Iterable[SegmentPlan]:
    """Yield non-title segments in render order for the body pass."""
    for unit in iter_shot_render_units(plan):
        for render_segment in unit.segments:
            yield render_segment.segment


def segment_render_duration(
    segment: SegmentPlan,
    result: SegmentResult | None,
    render_segment: RenderSegment | None = None,
    *,
    default: float,
) -> float:
    """Choose the visible duration for a rendered segment.

    Renderer-produced or asset-derived timing wins. Silent timed segments can then
    consume the segment target duration. Voiceover segments are driven by
    manim-voiceover/audio playback instead of target budgets.
    """
    if result is not None:
        result_duration = result.end - result.start
        if result_duration > 0:
            return result_duration
        if result.audio and result.audio.duration > 0:
            return result.audio.duration

    target_duration = (
        render_segment.target_duration
        if render_segment is not None
        else segment.target_duration
    )
    if (
        not segment_uses_voiceover(segment)
        and segment_consumes_timeline_duration(segment)
        and target_duration > 0
    ):
        return target_duration

    return default


def voiceover_segment_ids(plan: PlanManifest) -> set[str]:
    """Return segment IDs that should use CachedVoiceService."""
    return {
        segment.id
        for segment in iter_scene_render_segments(plan)
        if segment_uses_voiceover(segment)
    }


def segment_uses_voiceover(segment: SegmentPlan) -> bool:
    """Return whether a segment should ask manim-voiceover for audio."""
    return (
        segment.audio_request is not None
        and segment.segment_type not in TITLE_SEGMENT_TYPES
        and segment.segment_type not in MARKER_SEGMENT_TYPES
    )


def validate_renderer_visual_types(plan: PlanManifest) -> None:
    """Reject visual_type values that name render backends, not visual providers."""
    for scene in plan.scenes:
        if scene.visual_type in RENDER_BACKEND_ONLY_VISUAL_TYPES:
            raise ValueError(
                "Unsupported visual_type for scene "
                f"{scene.id}: {scene.visual_type}. "
                f"{scene.visual_type} is a render backend, not a visual provider."
            )
    for segment in plan.segments:
        if segment.visual_type in RENDER_BACKEND_ONLY_VISUAL_TYPES:
            raise ValueError(
                "Unsupported visual_type for segment "
                f"{segment.id}: {segment.visual_type}. "
                f"{segment.visual_type} is a render backend, not a visual provider."
            )


def validate_renderer_inputs(plan: PlanManifest, assets: ExecutionAssets) -> None:
    """Fail fast on renderer input contract violations before Manim starts."""
    validate_renderer_visual_types(plan)

    marker_segment_ids = sorted(
        segment.id
        for segment in plan.segments
        if segment.segment_type in MARKER_SEGMENT_TYPES
    )
    if marker_segment_ids:
        raise ValueError(
            "Renderer input contains marker segments; markers must be lowered "
            f"to shot cues: {marker_segment_ids}"
        )

    # Force structure, unknown shot segment references, and marker-as-segment
    # violations to fail before the Manim subprocess.
    render_units = list(iter_shot_render_units(plan, include_title_segments=True))

    covered_ids = {
        render_segment.segment.id
        for unit in render_units
        for render_segment in unit.segments
    }
    renderable_ids = {
        segment.id
        for segment in plan.segments
        if segment.segment_type not in MARKER_SEGMENT_TYPES
    }
    orphan_ids = sorted(renderable_ids - covered_ids)
    if orphan_ids:
        raise ValueError(
            "Renderer input has renderable segments not covered by shots: "
            f"{orphan_ids}"
        )

    required_audio_ids = {
        segment.id
        for segment in iter_scene_render_segments(plan)
        if segment_uses_voiceover(segment)
    }
    available_audio_ids = {
        asset.segment_id
        for asset in assets.audio_assets
        if asset.path
    }
    missing_audio_ids = sorted(required_audio_ids - available_audio_ids)
    if missing_audio_ids:
        raise ValueError(
            "Renderer input missing audio assets for segments: "
            f"{missing_audio_ids}"
        )
