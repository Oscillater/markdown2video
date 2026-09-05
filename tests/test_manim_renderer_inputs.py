"""Renderer input loading tests."""
from __future__ import annotations

import json

import pytest

from md2video.manifest.schema import (
    AudioAsset,
    AudioResult,
    AudioRequest,
    ExecutionAssets,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    SegmentResult,
    ShotPlan,
)
from md2video.layout import create_default_layout_registry
from md2video.tools.render.manifest_loader import load_manifests_from_env
from md2video.tools.render.manim_renderer_inputs import (
    iter_shot_render_units,
    iter_scene_render_segments,
    segment_render_duration,
    segment_uses_voiceover,
    shot_layout_context,
    title_layout_parts,
    title_layout_positions,
    validate_renderer_inputs,
    voiceover_segment_ids,
)


def _unit(layout_type: str, layout_params=None):
    from md2video.tools.render.manim_renderer_inputs import ShotRenderUnit

    return ShotRenderUnit(
        scene_id="scene_001",
        shot_id="shot_001",
        segments=(),
        cues=(),
        layout_type=layout_type,
        layout_params=dict(layout_params or {}),
    )



def test_shot_layout_context_center_title_body_places_body_region():
    ctx = shot_layout_context(_unit("center_title_body"), 4.5, 8.0)

    assert ctx.body is not None
    assert ctx.body.name == "body"
    assert ctx.body.center == pytest.approx((0.0, -0.96, 0.0))
    assert ctx.body.max_width == pytest.approx(3.78)
    assert ctx.has_image_region is False


def test_shot_layout_context_image_top_text_bottom_uses_text_region():
    ctx = shot_layout_context(
        _unit("image_top_text_bottom", {"split": "balanced", "gap": "normal"}),
        4.5,
        8.0,
    )

    assert ctx.body is not None
    assert ctx.body.name == "text"
    # text box: y 0.54..0.94 -> center y units (0.5 - 0.74) * 8
    assert ctx.body.center == pytest.approx((0.0, -1.92, 0.0))
    assert ctx.body.max_height == pytest.approx(3.2)
    assert ctx.has_image_region is True


def test_shot_layout_context_full_bleed_uses_caption_region():
    ctx = shot_layout_context(_unit("full_bleed_image_caption_bottom"), 4.5, 8.0)

    assert ctx.body is not None
    assert ctx.body.name == "caption"
    assert ctx.has_image_region is True


def test_shot_layout_context_unknown_layout_fails_fast():
    with pytest.raises(ValueError, match="Unknown layout_type"):
        shot_layout_context(_unit("does_not_exist"), 4.5, 8.0)


def test_title_layout_positions_stack_inside_title_region():
    positions = title_layout_positions(
        create_default_layout_registry().compute("center_title_body", {}, 480, 854),
        4.5,
        8.0,
    )

    assert positions is not None
    # title box: y 0.06..0.26 -> center y units 2.72, height 1.6
    assert positions["main"] == pytest.approx((0.0, 3.12, 0.0))
    assert positions["sub"] == pytest.approx((0.0, 2.32, 0.0))


def test_title_layout_positions_none_without_title_region():
    positions = title_layout_positions(
        create_default_layout_registry().compute("full_bleed_image_caption_bottom", {}, 480, 854),
        4.5,
        8.0,
    )

    assert positions is None


def test_load_manifests_from_explicit_env(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    assets_path = tmp_path / "execution-assets.json"
    timeline_path = tmp_path / "timeline.json"
    plan_path.write_text(
        json.dumps({
            "version": "1",
            "segments": [{"id": "seg_001", "text": "hello", "segment_type": "content"}],
            "scenes": [],
        }),
        encoding="utf-8",
    )
    assets_path.write_text(
        json.dumps({
            "version": "1",
            "audio_assets": [],
            "visual_assets": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("MD2VIDEO_PLAN_PATH", str(plan_path))
    monkeypatch.setenv("MD2VIDEO_EXECUTION_ASSETS_PATH", str(assets_path))
    monkeypatch.setenv("MD2VIDEO_TIMELINE_PATH", str(timeline_path))

    plan, result = load_manifests_from_env()

    assert plan.segments[0].id == "seg_001"
    assert result.segments[0].id == "seg_001"


def test_load_manifests_requires_timeline_env(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    assets_path = tmp_path / "execution-assets.json"
    plan_path.write_text('{"version":"1","segments":[],"scenes":[]}', encoding="utf-8")
    assets_path.write_text(
        '{"version":"1","audio_assets":[],"visual_assets":[]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MD2VIDEO_PLAN_PATH", str(plan_path))
    monkeypatch.setenv("MD2VIDEO_EXECUTION_ASSETS_PATH", str(assets_path))
    monkeypatch.delenv("MD2VIDEO_TIMELINE_PATH", raising=False)

    with pytest.raises(FileNotFoundError, match="MD2VIDEO_TIMELINE_PATH is required"):
        load_manifests_from_env()


def test_load_manifests_does_not_fallback_to_result_json(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "result.json"
    timeline_path = tmp_path / "timeline.json"
    plan_path.write_text('{"version":"1","segments":[],"scenes":[]}', encoding="utf-8")
    result_path.write_text('{"segments":[],"scenes":[]}', encoding="utf-8")
    monkeypatch.setenv("MD2VIDEO_PLAN_PATH", str(plan_path))
    monkeypatch.delenv("MD2VIDEO_EXECUTION_ASSETS_PATH", raising=False)
    monkeypatch.setenv("MD2VIDEO_TIMELINE_PATH", str(timeline_path))

    with pytest.raises(FileNotFoundError, match="MD2VIDEO_EXECUTION_ASSETS_PATH is required"):
        load_manifests_from_env()


def test_title_layout_parts_main_only_is_centered():
    title = SegmentPlan(id="title", text="Title", segment_type="title_main")

    parts = title_layout_parts(title, None, main_font_size=40, sub_font_size=30)

    assert len(parts) == 1
    assert parts[0].segment is title
    assert parts[0].font_size == 40
    assert parts[0].position == (0.0, 0.0, 0.0)


def test_title_layout_parts_subtitle_only_is_centered():
    subtitle = SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub")

    parts = title_layout_parts(None, subtitle, main_font_size=40, sub_font_size=30)

    assert len(parts) == 1
    assert parts[0].segment is subtitle
    assert parts[0].font_size == 30
    assert parts[0].position == (0.0, 0.0, 0.0)


def test_title_layout_parts_main_and_subtitle_keep_stacked_layout():
    title = SegmentPlan(id="title", text="Title", segment_type="title_main")
    subtitle = SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub")

    parts = title_layout_parts(title, subtitle, main_font_size=40, sub_font_size=30)

    assert [(part.segment.id, part.font_size, part.position) for part in parts] == [
        ("title", 40, (0.0, 1.0, 0.0)),
        ("subtitle", 30, (0.0, -1.0, 0.0)),
    ]


def test_iter_scene_render_segments_keeps_body_in_title_scene():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="title", text="Title", segment_type="title_main"),
            SegmentPlan(id="body", text="Body", segment_type="content"),
            SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["title", "body", "subtitle"],
                    ),
                ],
            ),
        ],
    )

    assert [segment.id for segment in iter_scene_render_segments(plan)] == ["body"]


def test_iter_scene_render_segments_title_only_scene_yields_no_body():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="title", text="Title", segment_type="title_main"),
            SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub"),
        ],
        scenes=[
            ScenePlan(
                id="scene_title",
                shots=[
                    ShotPlan(
                        id="shot_title",
                        segment_ids=["title", "subtitle"],
                    ),
                ],
            ),
        ],
    )

    assert list(iter_scene_render_segments(plan)) == []


def test_iter_scene_render_segments_fails_on_unknown_segment_id():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="body", text="Body", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["body", "missing_segment"],
                    ),
                ],
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="scene_001.*shot_001.*missing_segment",
    ):
        list(iter_scene_render_segments(plan))


def test_iter_scene_render_segments_preserves_scene_shot_segment_order():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="one", segment_type="content"),
            SegmentPlan(id="seg_002", text="two", segment_type="content"),
            SegmentPlan(id="seg_003", text="three", segment_type="appendix"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_002"]),
                    ShotPlan(id="shot_002", segment_ids=["seg_001"]),
                ],
            ),
            ScenePlan(
                id="scene_002",
                shots=[
                    ShotPlan(id="shot_003", segment_ids=["seg_003"]),
                ],
            ),
        ],
    )

    assert [segment.id for segment in iter_scene_render_segments(plan)] == [
        "seg_002",
        "seg_001",
        "seg_003",
    ]


def test_iter_shot_render_units_uses_shot_order_not_plan_segment_order():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_a", text="A", segment_type="content"),
            SegmentPlan(id="seg_b", text="B", segment_type="content"),
            SegmentPlan(id="seg_c", text="C", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_c", "seg_a"]),
                    ShotPlan(id="shot_002", segment_ids=["seg_b"]),
                ],
            ),
        ],
    )

    units = list(iter_shot_render_units(plan))

    assert [unit.segment_ids for unit in units] == [["seg_c", "seg_a"], ["seg_b"]]
    assert [(unit.scene_id, unit.shot_id) for unit in units] == [
        ("scene_001", "shot_001"),
        ("scene_001", "shot_002"),
    ]


def test_iter_shot_render_units_preserves_segment_order_across_multiple_shots():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="one", segment_type="content"),
            SegmentPlan(id="seg_002", text="two", segment_type="content"),
            SegmentPlan(id="seg_003", text="three", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_002", "seg_001"]),
                    ShotPlan(id="shot_002", segment_ids=["seg_003"]),
                ],
            ),
        ],
    )

    assert [
        (unit.shot_id, unit.segment_ids)
        for unit in iter_shot_render_units(plan)
    ] == [
        ("shot_001", ["seg_002", "seg_001"]),
        ("shot_002", ["seg_003"]),
    ]


def test_iter_shot_render_units_fails_on_unknown_segment_id():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="body", text="Body", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["body", "missing_segment"]),
                ],
            ),
        ],
    )

    with pytest.raises(ValueError, match="scene_001.*shot_001.*missing_segment"):
        list(iter_shot_render_units(plan))


def test_iter_shot_render_units_skips_title_but_keeps_same_shot_content():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="title", text="Title", segment_type="title_main"),
            SegmentPlan(id="body", text="Body", segment_type="content", target_duration=3.0),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["title", "body"],
                    ),
                ],
            ),
        ],
    )

    units = list(iter_shot_render_units(plan))

    assert [unit.segment_ids for unit in units] == [["body"]]
    assert units[0].scene_id == "scene_001"
    assert units[0].shot_id == "shot_001"
    assert units[0].segments[0].target_duration == 3.0


def test_iter_shot_render_units_carries_marker_cues_without_audio():
    body = SegmentPlan(id="body", text="Body", segment_type="content")
    plan = PlanManifest(
        segments=[body],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["body"],
                        cues=[{
                            "id": "marker",
                            "cue_type": "marker_image",
                            "kind": "start",
                            "name": "hero",
                            "position": "before",
                            "anchor_segment_id": "body",
                        }],
                    ),
                ],
            ),
        ],
    )

    units = list(iter_shot_render_units(plan))

    assert [unit.segment_ids for unit in units] == [["body"]]
    assert units[0].cues[0]["id"] == "marker"
    validate_renderer_inputs(plan, ExecutionAssets())


def test_segment_render_duration_uses_result_duration_before_shot_target():
    segment = SegmentPlan(
        id="seg_001",
        text="silent",
        segment_type="content",
        target_duration=9.0,
    )
    plan = PlanManifest(
        segments=[segment],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_001"]),
                ],
            ),
        ],
    )
    unit = next(iter(iter_shot_render_units(plan)))
    result = SegmentResult(id="seg_001", start=2.0, end=3.25)

    assert segment_render_duration(segment, result, unit.segments[0], default=2.0) == 1.25


def test_segment_render_duration_uses_silent_header_and_content_targets():
    header = SegmentPlan(
        id="header",
        text="Header",
        segment_type="section_header",
        target_duration=2.0,
    )
    content = SegmentPlan(
        id="content",
        text="Content",
        segment_type="content",
        target_duration=4.0,
    )
    plan = PlanManifest(
        segments=[header, content],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["header", "content"]),
                ],
            ),
        ],
    )
    units = list(iter_shot_render_units(plan))

    assert [
        segment_render_duration(item.segment, None, item, default=2.0)
        for item in units[0].segments
    ] == [2.0, 4.0]


def test_segment_render_duration_keeps_voiceover_on_audio_result_not_shot_target():
    segment = SegmentPlan(
        id="seg_001",
        text="voiced",
        segment_type="content",
        target_duration=9.0,
        audio_request=AudioRequest(),
    )
    plan = PlanManifest(
        segments=[segment],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_001"]),
                ],
            ),
        ],
    )
    unit = next(iter(iter_shot_render_units(plan)))
    result = SegmentResult(
        id="seg_001",
        audio=AudioResult(path="voice.wav", duration=1.5),
        start=0.0,
        end=1.5,
    )

    assert segment_render_duration(segment, result, unit.segments[0], default=2.0) == 1.5
    assert segment_render_duration(segment, None, unit.segments[0], default=0.0) == 0.0


def test_iter_shot_render_units_carries_scene_layout_contract():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="Body", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                layout_type="image_top_text_bottom",
                layout_params={"split": "text_focus", "gap": "wide"},
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_001"]),
                ],
            ),
        ],
    )

    unit = next(iter(iter_shot_render_units(plan)))

    assert unit.layout_type == "image_top_text_bottom"
    assert unit.layout_params == {"split": "text_focus", "gap": "wide"}


def test_renderer_input_helper_carries_invalid_layout_for_registry_to_reject():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="Body", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                layout_type="missing_layout",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_001"]),
                ],
            ),
        ],
    )

    unit = next(iter(iter_shot_render_units(plan)))

    assert unit.layout_type == "missing_layout"
    validate_renderer_inputs(plan, ExecutionAssets())
    with pytest.raises(ValueError, match="Unknown layout_type"):
        create_default_layout_registry().compute(unit.layout_type, unit.layout_params)


def test_validate_renderer_inputs_allows_silent_plan_without_audio_assets():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="header", text="Header", segment_type="section_header"),
            SegmentPlan(id="content", text="Content", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["header", "content"]),
                ],
            ),
        ],
    )

    validate_renderer_inputs(plan, ExecutionAssets())
    assert voiceover_segment_ids(plan) == set()


def test_segment_uses_voiceover_only_for_voiced_body_segments():
    assert segment_uses_voiceover(
        SegmentPlan(
            id="header",
            text="Header",
            segment_type="section_header",
            audio_request=AudioRequest(),
        )
    )
    assert segment_uses_voiceover(
        SegmentPlan(
            id="content",
            text="Content",
            segment_type="content",
            audio_request=AudioRequest(),
        )
    )
    assert not segment_uses_voiceover(
        SegmentPlan(
            id="silent",
            text="Silent",
            segment_type="content",
            audio_request=None,
        )
    )
    assert not segment_uses_voiceover(
        SegmentPlan(
            id="title",
            text="Title",
            segment_type="title_main",
            audio_request=AudioRequest(),
        )
    )
    assert not segment_uses_voiceover(
        SegmentPlan(
            id="marker",
            text="[music_start bgm]",
            segment_type="marker_music",
            audio_request=AudioRequest(),
        )
    )


def test_validate_renderer_inputs_requires_audio_assets_for_voiced_segments():
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="header",
                text="Header",
                segment_type="section_header",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="content",
                text="Content",
                segment_type="content",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="silent",
                text="Silent",
                segment_type="content",
                audio_request=None,
            ),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["header", "content", "silent"],
                    ),
                ],
            ),
        ],
    )

    with pytest.raises(ValueError, match="content.*header"):
        validate_renderer_inputs(plan, ExecutionAssets())

    validate_renderer_inputs(
        plan,
        ExecutionAssets(audio_assets=[
            AudioAsset(segment_id="header", path="header.wav", duration=1.0),
            AudioAsset(segment_id="content", path="content.wav", duration=1.0),
        ]),
    )


def test_validate_renderer_inputs_does_not_require_audio_for_title_or_marker_cue():
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="title",
                text="Title",
                segment_type="title_main",
                audio_request=AudioRequest(),
            ),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(
                        id="shot_001",
                        segment_ids=["title"],
                        cues=[{
                            "id": "marker",
                            "cue_type": "marker_music",
                            "kind": "start",
                            "name": "bgm",
                        }],
                    ),
                ],
            ),
        ],
    )

    validate_renderer_inputs(plan, ExecutionAssets())


def test_validate_renderer_inputs_rejects_marker_segments():
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="marker",
                text="[music_start bgm]",
                segment_type="marker_music",
            ),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[ShotPlan(id="shot_001", cues=[{"id": "marker", "cue_type": "marker_music"}])],
            ),
        ],
    )

    with pytest.raises(ValueError, match="marker segments.*marker"):
        validate_renderer_inputs(plan, ExecutionAssets())


def test_validate_renderer_inputs_rejects_manim_visual_type():
    plan = PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="Body", segment_type="content"),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                visual_type="manim",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["seg_001"]),
                ],
            ),
        ],
    )

    with pytest.raises(ValueError, match="Unsupported visual_type.*scene_001.*manim"):
        validate_renderer_inputs(plan, ExecutionAssets())
