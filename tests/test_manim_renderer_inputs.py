"""Renderer input loading tests."""
from __future__ import annotations

import json

import pytest

from md2video.manifest.schema import (
    AudioAsset,
    AudioRequest,
    ExecutionAssets,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    ShotPlan,
)
from md2video.tools.render.manifest_loader import load_manifests_from_env
from md2video.tools.render.manim_renderer_inputs import (
    iter_scene_render_segments,
    segment_uses_voiceover,
    title_layout_parts,
    validate_renderer_inputs,
)
from md2video.tools.render.timeline_builder import build_shot_timeline


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


def test_build_shot_timeline_includes_marker_only_shots():
    shots = build_shot_timeline(
        text_timeline=[{
            "segment_id": "seg_001",
            "scene_id": "scene_001",
            "shot_id": "shot_001",
            "start": 0.0,
            "end": 2.0,
        }],
        marker_timeline=[{
            "segment_id": "marker_001",
            "scene_id": "scene_002",
            "shot_id": "shot_002",
            "time": 2.0,
        }],
    )

    assert shots == [
        {
            "shot_id": "shot_001",
            "scene_id": "scene_001",
            "segment_ids": ["seg_001"],
            "start": 0.0,
            "end": 2.0,
        },
        {
            "shot_id": "shot_002",
            "scene_id": "scene_002",
            "segment_ids": ["marker_001"],
            "start": 2.0,
            "end": 2.0,
        },
    ]


def test_title_layout_parts_main_only_is_centered():
    title = SegmentPlan(id="title", text="Title", segment_type="title_main")

    parts = title_layout_parts(title, None)

    assert len(parts) == 1
    assert parts[0].segment is title
    assert parts[0].font_size == 40
    assert parts[0].position == (0.0, 0.0, 0.0)


def test_title_layout_parts_subtitle_only_is_centered():
    subtitle = SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub")

    parts = title_layout_parts(None, subtitle)

    assert len(parts) == 1
    assert parts[0].segment is subtitle
    assert parts[0].font_size == 30
    assert parts[0].position == (0.0, 0.0, 0.0)


def test_title_layout_parts_main_and_subtitle_keep_stacked_layout():
    title = SegmentPlan(id="title", text="Title", segment_type="title_main")
    subtitle = SegmentPlan(id="subtitle", text="Subtitle", segment_type="title_sub")

    parts = title_layout_parts(title, subtitle)

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


def test_validate_renderer_inputs_does_not_require_audio_for_title_or_marker():
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="title",
                text="Title",
                segment_type="title_main",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="marker",
                text="[music_start bgm]",
                segment_type="marker_music",
                audio_request=AudioRequest(),
            ),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[
                    ShotPlan(id="shot_001", segment_ids=["title", "marker"]),
                ],
            ),
        ],
    )

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
