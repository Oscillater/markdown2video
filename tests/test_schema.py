"""Tests for md2video.manifest.schema Pydantic models."""
from __future__ import annotations

import json

from md2video.manifest.schema import (
    AudioAsset,
    AudioRequest,
    AudioResult,
    ExecutionAssets,
    FinalResultManifest,
    PlanManifest,
    ResultManifest,
    ScenePlan,
    SceneResult,
    SegmentPlan,
    SegmentResult,
    ShotPlan,
    ShotResult,
    VisualAsset,
    VisualResult,
    result_manifest_from_execution_assets,
)


# ========== AudioRequest ==========


class TestAudioRequest:
    def test_defaults(self):
        req = AudioRequest()
        assert req.voice == "zh-CN-YunxiNeural"
        assert req.speed == 1.0
        assert req.format == "wav"

    def test_custom_values(self):
        req = AudioRequest(voice="en-US-JennyNeural", speed=1.5, format="mp3")
        assert req.voice == "en-US-JennyNeural"
        assert req.speed == 1.5
        assert req.format == "mp3"


# ========== SegmentPlan ==========


class TestSegmentPlan:
    def test_defaults(self):
        seg = SegmentPlan(id="s1", text="x", segment_type="content")
        assert seg.visual_type == "text_only"
        assert seg.visual_params == {}
        assert seg.layout_type == "center_title_body"
        assert seg.layout_params == {}
        assert seg.audio_request is None
        assert seg.explicit is False
        assert seg.section_context == ""
        assert seg.marker_data is None

    def test_explicit_preserves_visual_type(self):
        seg = SegmentPlan(
            id="s1", text="x", segment_type="content",
            explicit=True, visual_type="custom",
        )
        assert seg.explicit is True
        assert seg.visual_type == "custom"

    def test_custom_layout(self):
        seg = SegmentPlan(
            id="s1", text="x", segment_type="content",
            layout_type="image_top_text_bottom",
            layout_params={"split": "image_focus"},
        )
        assert seg.layout_type == "image_top_text_bottom"
        assert seg.layout_params == {"split": "image_focus"}

    def test_marker_data(self):
        seg = SegmentPlan(
            id="s1", text="[music_start bgm]", segment_type="marker_music",
            marker_data={"kind": "start", "name": "bgm"},
        )
        assert seg.marker_data == {"kind": "start", "name": "bgm"}

    def test_any_segment_type_string_accepted(self):
        seg = SegmentPlan(id="s1", text="x", segment_type="invalid_type")
        assert seg.segment_type == "invalid_type"


# ========== PlanManifest ==========


class TestPlanManifest:
    def test_defaults(self):
        m = PlanManifest()
        assert m.version == "1"
        assert m.segments == []
        assert m.media_declarations == {}

    def test_with_segments(self):
        seg = SegmentPlan(id="s1", text="x", segment_type="content")
        m = PlanManifest(segments=[seg])
        assert len(m.segments) == 1
        assert m.segments[0].id == "s1"

    def test_media_declarations_music(self):
        m = PlanManifest(
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        assert m.media_declarations["music"]["bgm"] == "./music.mp3"

    def test_round_trip_json(self):
        original = PlanManifest(
            segments=[
                SegmentPlan(
                    id="s1", text="标题", segment_type="title_main",
                    audio_request=AudioRequest(voice="en-US-JennyNeural"),
                ),
            ],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        json_str = original.model_dump_json()
        restored = PlanManifest.model_validate_json(json_str)
        assert restored.version == original.version
        assert len(restored.segments) == len(original.segments)
        assert restored.segments[0].text == original.segments[0].text
        assert restored.segments[0].audio_request.voice == "en-US-JennyNeural"
        assert restored.media_declarations == original.media_declarations


# ========== AudioResult ==========


class TestAudioResult:
    def test_creation(self):
        r = AudioResult(path="/audio.wav", duration=3.5)
        assert r.path == "/audio.wav"
        assert r.duration == 3.5
        assert r.provider == "edge-tts"
        assert r.cache_key == ""

    def test_with_cache_key(self):
        r = AudioResult(path="/a.wav", duration=1.0, cache_key="abc123")
        assert r.cache_key == "abc123"


# ========== VisualResult ==========


class TestVisualResult:
    def test_defaults(self):
        v = VisualResult()
        assert v.path == ""
        assert v.width == 0
        assert v.height == 0
        assert v.source == "none"


# ========== SegmentResult ==========


class TestSegmentResult:
    def test_defaults(self):
        sr = SegmentResult(id="s1", start=1.0, end=3.5)
        assert sr.audio is None
        assert isinstance(sr.visual, VisualResult)
        assert sr.visual.source == "none"

    def test_with_audio(self):
        audio = AudioResult(path="/a.wav", duration=2.0, cache_key="k1")
        sr = SegmentResult(id="s1", start=0.0, end=2.0, audio=audio)
        assert sr.audio.path == "/a.wav"
        assert sr.audio.duration == 2.0


# ========== ResultManifest ==========


class TestResultManifest:
    def test_defaults(self):
        m = ResultManifest()
        assert m.segments == []

    def test_serialization_round_trip(self):
        original = ResultManifest(
            segments=[
                SegmentResult(
                    id="s1", start=0.0, end=2.0,
                    audio=AudioResult(path="s1.wav", duration=2.0),
                ),
            ],
        )
        json_str = original.model_dump_json()
        restored = ResultManifest.model_validate_json(json_str)
        assert len(restored.segments) == 1
        assert restored.segments[0].id == "s1"
        assert restored.segments[0].audio.path == "s1.wav"


# ========== ShotPlan ==========


class TestShotPlan:
    def test_defaults(self):
        sp = ShotPlan(id="shot_001")
        assert sp.segment_ids == []
        assert sp.target_duration == 0.0

    def test_with_segments(self):
        sp = ShotPlan(id="shot_001", segment_ids=["seg_001", "seg_002"])
        assert sp.segment_ids == ["seg_001", "seg_002"]

    def test_target_duration(self):
        sp = ShotPlan(id="shot_001", segment_ids=["seg_001"], target_duration=5.5)
        assert sp.target_duration == 5.5

    def test_json_round_trip(self):
        original = ShotPlan(id="shot_001", segment_ids=["seg_001"], target_duration=3.0)
        json_str = original.model_dump_json()
        restored = ShotPlan.model_validate_json(json_str)
        assert restored.id == "shot_001"
        assert restored.segment_ids == ["seg_001"]
        assert restored.target_duration == 3.0

    def test_backward_compat_no_target_duration(self):
        """旧 JSON 无 target_duration 字段应正常解析。"""
        json_str = '{"id":"shot_001","segment_ids":["seg_001"]}'
        sp = ShotPlan.model_validate_json(json_str)
        assert sp.target_duration == 0.0


# ========== ShotResult ==========


class TestShotResult:
    def test_defaults(self):
        sr = ShotResult(id="shot_001")
        assert sr.segment_ids == []
        assert sr.start == 0.0
        assert sr.end == 0.0
        assert sr.visual.source == "none"

    def test_with_visual(self):
        sr = ShotResult(
            id="shot_001",
            segment_ids=["seg_001"],
            start=0.0,
            end=5.5,
            visual=VisualResult(path="bg.jpg", width=1080, height=1920, source="pexels"),
        )
        assert sr.visual.path == "bg.jpg"
        assert sr.visual.source == "pexels"

    def test_json_round_trip(self):
        original = ShotResult(id="shot_001", segment_ids=["seg_001"], start=1.0, end=8.5)
        json_str = original.model_dump_json()
        restored = ShotResult.model_validate_json(json_str)
        assert restored.id == "shot_001"
        assert restored.segment_ids == ["seg_001"]
        assert restored.start == 1.0
        assert restored.end == 8.5


# ========== ScenePlan ==========


class TestScenePlan:
    def test_defaults(self):
        sp = ScenePlan(id="scene_001")
        assert sp.visual_type == "text_only"
        assert sp.visual_params == {}
        assert sp.layout_type == "center_title_body"
        assert sp.layout_params == {}
        assert sp.shots == []
        assert sp.all_segment_ids == []
        assert sp.section_context == ""

    def test_with_segments(self):
        sp = ScenePlan(
            id="scene_001",
            shots=[ShotPlan(id="shot_001", segment_ids=["seg_001", "seg_002"])],
            section_context="小重山",
        )
        assert sp.shots[0].segment_ids == ["seg_001", "seg_002"]
        assert sp.all_segment_ids == ["seg_001", "seg_002"]
        assert sp.section_context == "小重山"

    def test_custom_visual_type(self):
        sp = ScenePlan(
            id="scene_001",
            visual_type="stock_image",
            visual_params={"query": "neural network", "fallback": "text_only"},
        )
        assert sp.visual_type == "stock_image"
        assert sp.visual_params["query"] == "neural network"

    def test_custom_layout_type(self):
        sp = ScenePlan(
            id="scene_001",
            layout_type="full_bleed_image_caption_bottom",
            layout_params={"caption_size": "compact"},
        )
        assert sp.layout_type == "full_bleed_image_caption_bottom"
        assert sp.layout_params == {"caption_size": "compact"}

    def test_json_round_trip(self):
        original = ScenePlan(
            id="scene_001",
            visual_type="stock_image",
            visual_params={"query": "test"},
            layout_type="image_top_text_bottom",
            layout_params={"split": "text_focus"},
            shots=[ShotPlan(id="shot_001", segment_ids=["seg_001", "seg_002"])],
            section_context="测试",
        )
        json_str = original.model_dump_json()
        restored = ScenePlan.model_validate_json(json_str)
        assert restored.id == "scene_001"
        assert restored.visual_type == "stock_image"
        assert restored.layout_type == "image_top_text_bottom"
        assert restored.layout_params == {"split": "text_focus"}
        assert restored.shots[0].segment_ids == ["seg_001", "seg_002"]
        assert restored.all_segment_ids == ["seg_001", "seg_002"]

    def test_backward_compat_segment_ids(self):
        """旧 JSON 含 segment_ids 时自动迁移为单 Shot。"""
        old_json = '{"id": "scene_001", "segment_ids": ["seg_001", "seg_002"]}'
        sp = ScenePlan.model_validate_json(old_json)
        assert len(sp.shots) == 1
        assert sp.shots[0].segment_ids == ["seg_001", "seg_002"]
        assert sp.all_segment_ids == ["seg_001", "seg_002"]
        assert sp.layout_type == "center_title_body"


# ========== SceneResult ==========


class TestSceneResult:
    def test_defaults(self):
        sr = SceneResult(id="scene_001")
        assert sr.shots == []
        assert sr.all_segment_ids == []
        assert sr.start == 0.0
        assert sr.end == 0.0

    def test_with_visual(self):
        sr = SceneResult(
            id="scene_001",
            shots=[ShotResult(
                id="shot_001", segment_ids=["seg_001"],
                start=0.0, end=5.5,
                visual=VisualResult(path="bg.jpg", width=1080, height=1920, source="pexels"),
            )],
        )
        assert sr.shots[0].visual.path == "bg.jpg"
        assert sr.shots[0].visual.source == "pexels"

    def test_json_round_trip(self):
        original = SceneResult(
            id="scene_001",
            shots=[ShotResult(id="shot_001", segment_ids=["seg_001", "seg_002"], start=1.0, end=8.5)],
        )
        json_str = original.model_dump_json()
        restored = SceneResult.model_validate_json(json_str)
        assert restored.id == "scene_001"
        assert restored.start == 1.0
        assert restored.end == 8.5
        assert restored.shots[0].segment_ids == ["seg_001", "seg_002"]
        assert restored.all_segment_ids == ["seg_001", "seg_002"]

    def test_backward_compat_segment_ids(self):
        """旧 JSON 含 segment_ids 时自动迁移为单 Shot。"""
        old_json = '{"id": "scene_001", "segment_ids": ["seg_001"], "start": 0.0, "end": 5.0}'
        sr = SceneResult.model_validate_json(old_json)
        assert len(sr.shots) == 1
        assert sr.shots[0].segment_ids == ["seg_001"]


# ========== PlanManifest with Scenes ==========


class TestPlanManifestWithScenes:
    def test_empty_scenes_default(self):
        m = PlanManifest()
        assert m.scenes == []

    def test_scenes_in_serialization(self):
        scene = ScenePlan(id="scene_001", shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])])
        m = PlanManifest(scenes=[scene])
        json_str = m.model_dump_json()
        restored = PlanManifest.model_validate_json(json_str)
        assert len(restored.scenes) == 1
        assert restored.scenes[0].id == "scene_001"
        assert restored.scenes[0].shots[0].segment_ids == ["seg_001"]

    def test_backward_compat_no_scenes_field(self):
        old_json = '{"version": "1", "segments": [], "media_declarations": {}}'
        m = PlanManifest.model_validate_json(old_json)
        assert m.scenes == []
        assert m.segments == []


# ========== ResultManifest with Scenes ==========


class TestResultManifestWithScenes:
    def test_empty_scenes_default(self):
        m = ResultManifest()
        assert m.scenes == []

    def test_scenes_in_serialization(self):
        scene = SceneResult(
            id="scene_001",
            shots=[ShotResult(id="shot_001", segment_ids=["seg_001"], start=0.0, end=5.0)],
        )
        m = ResultManifest(scenes=[scene])
        json_str = m.model_dump_json()
        restored = ResultManifest.model_validate_json(json_str)
        assert len(restored.scenes) == 1
        assert restored.scenes[0].start == 0.0
        assert restored.scenes[0].shots[0].segment_ids == ["seg_001"]

    def test_backward_compat_no_scenes_field(self):
        old_json = '{"segments": []}'
        m = ResultManifest.model_validate_json(old_json)
        assert m.scenes == []

    def test_write_then_read_preserves_scenes(self, tmp_path):
        """模拟 pipeline 写盘后读回，scenes 字段不能丢。"""
        scene = SceneResult(
            id="scene_001",
            shots=[ShotResult(id="shot_001", segment_ids=["seg_001", "seg_002"], start=0.0, end=9.0)],
        )
        m = ResultManifest(
            segments=[
                SegmentResult(id="seg_001", start=0.0, end=4.5),
                SegmentResult(id="seg_002", start=4.5, end=9.0),
            ],
            scenes=[scene],
        )
        # 写盘
        p = tmp_path / "result.json"
        p.write_text(m.model_dump_json(indent=2), encoding="utf-8")
        # 读回
        restored = ResultManifest.model_validate_json(p.read_text(encoding="utf-8"))
        assert len(restored.scenes) == 1
        assert restored.scenes[0].id == "scene_001"
        assert restored.scenes[0].shots[0].segment_ids == ["seg_001", "seg_002"]
        assert restored.scenes[0].end == 9.0


# ========== Runtime Artifacts ==========


class TestExecutionAssets:
    def test_round_trip_json(self):
        assets = ExecutionAssets(
            audio_assets=[
                AudioAsset(
                    segment_id="seg_001",
                    path="artifacts/tts/seg_001.wav",
                    duration=2.5,
                    cache_key="audio-key",
                ),
            ],
            visual_assets=[
                VisualAsset(
                    shot_id="shot_001",
                    path="assets/local_image.jpg",
                    width=500,
                    height=631,
                    provider="local",
                    cache_key="visual-key",
                ),
            ],
        )

        restored = ExecutionAssets.model_validate_json(assets.model_dump_json())
        assert restored.version == "1"
        assert restored.audio_assets[0].segment_id == "seg_001"
        assert restored.visual_assets[0].provider == "local"
        assert restored.visual_assets[0].cache_key == "visual-key"

    def test_result_manifest_adapter_uses_audio_and_visual_assets(self):
        plan = PlanManifest(
            segments=[SegmentPlan(id="seg_001", text="x", segment_type="content")],
            scenes=[
                ScenePlan(
                    id="scene_001",
                    visual_type="stock_image",
                    shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])],
                ),
            ],
        )
        assets = ExecutionAssets(
            audio_assets=[AudioAsset(segment_id="seg_001", path="a.wav", duration=3.0)],
            visual_assets=[VisualAsset(shot_id="shot_001", path="img.jpg", provider="local")],
        )

        result = result_manifest_from_execution_assets(plan, assets)
        assert result.segments[0].audio.path == "a.wav"
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 3.0
        assert result.scenes[0].shots[0].visual.path == "img.jpg"
        assert result.scenes[0].shots[0].visual.source == "local"

    def test_result_manifest_adapter_uses_target_duration_without_audio(self):
        plan = PlanManifest(
            segments=[SegmentPlan(id="seg_001", text="x", segment_type="content")],
            scenes=[
                ScenePlan(
                    id="scene_001",
                    visual_type="stock_image",
                    shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"], target_duration=2.0)],
                ),
            ],
        )

        result = result_manifest_from_execution_assets(plan, ExecutionAssets())
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 2.0
        assert result.scenes[0].shots[0].start == 0.0
        assert result.scenes[0].shots[0].end == 2.0

    def test_result_manifest_adapter_keeps_silent_then_voiced_shots_monotonic(self):
        plan = PlanManifest(
            segments=[
                SegmentPlan(id="seg_001", text="silent", segment_type="content"),
                SegmentPlan(id="seg_002", text="voiced", segment_type="content"),
            ],
            scenes=[
                ScenePlan(
                    id="scene_001",
                    shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"], target_duration=2.0)],
                ),
                ScenePlan(
                    id="scene_002",
                    shots=[ShotPlan(id="shot_002", segment_ids=["seg_002"])],
                ),
            ],
        )
        assets = ExecutionAssets(
            audio_assets=[
                AudioAsset(segment_id="seg_002", path="voice.wav", duration=1.0),
            ],
        )

        result = result_manifest_from_execution_assets(plan, assets)

        by_segment = {segment.id: segment for segment in result.segments}
        assert by_segment["seg_001"].start == 0.0
        assert by_segment["seg_001"].end == 2.0
        assert by_segment["seg_002"].start == 2.0
        assert by_segment["seg_002"].end == 3.0

        assert result.scenes[0].shots[0].start == 0.0
        assert result.scenes[0].shots[0].end == 2.0
        assert result.scenes[1].shots[0].start == 2.0
        assert result.scenes[1].shots[0].end == 3.0


class TestFinalResultManifest:
    def test_round_trip_json(self):
        result = FinalResultManifest(
            output_mp4="artifacts/no_key_demo.mp4",
            used_assets={"visual": [{"shot_id": "shot_001", "path": "img.jpg"}]},
            artifact_index={"plan": "artifacts/plan.json"},
        )
        restored = FinalResultManifest.model_validate_json(result.model_dump_json())
        assert restored.output_mp4 == "artifacts/no_key_demo.mp4"
        assert restored.used_assets["visual"][0]["shot_id"] == "shot_001"
