"""Pure input helpers for the Manim renderer."""
from __future__ import annotations

from typing import Iterable, NamedTuple

from md2video.config import RENDER_BACKEND_ONLY_VISUAL_TYPES
from md2video.manifest.schema import ExecutionAssets, PlanManifest, SegmentPlan


TITLE_SEGMENT_TYPES = {"title_main", "title_sub"}
MARKER_SEGMENT_TYPES = {"marker_music", "marker_image"}


class TitleLayoutPart(NamedTuple):
    segment: SegmentPlan
    font_size: int
    position: tuple[float, float, float]


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


def iter_scene_render_segments(plan: PlanManifest) -> Iterable[SegmentPlan]:
    """Yield non-title segments in render order for the body pass."""
    segment_by_id = {segment.id: segment for segment in plan.segments}

    if not plan.scenes:
        for segment in plan.segments:
            if segment.segment_type not in TITLE_SEGMENT_TYPES:
                yield segment
        return

    for scene in plan.scenes:
        for shot in scene.shots:
            for segment_id in shot.segment_ids:
                segment = segment_by_id.get(segment_id)
                if segment is None:
                    raise ValueError(
                        "Renderer input references unknown segment_id "
                        f"in scene {scene.id}, shot {shot.id}: {segment_id}"
                    )
                if segment.segment_type in TITLE_SEGMENT_TYPES:
                    continue
                yield segment


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

    # Force unknown shot segment references to fail before the Manim subprocess.
    for _ in iter_scene_render_segments(plan):
        pass

    required_audio_ids = {
        segment.id
        for segment in plan.segments
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
