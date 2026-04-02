"""Tests for md2video.manifest.schema Pydantic models."""
from __future__ import annotations

import json

from md2video.manifest.schema import (
    AudioRequest,
    AudioResult,
    PlanManifest,
    ResultManifest,
    ScenePlan,
    SceneResult,
    SegmentPlan,
    SegmentResult,
    VisualResult,
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


# ========== ScenePlan ==========


class TestScenePlan:
    def test_defaults(self):
        sp = ScenePlan(id="scene_001")
        assert sp.visual_type == "text_only"
        assert sp.visual_params == {}
        assert sp.segment_ids == []
        assert sp.section_context == ""

    def test_with_segments(self):
        sp = ScenePlan(
            id="scene_001",
            segment_ids=["seg_001", "seg_002"],
            section_context="小重山",
        )
        assert sp.segment_ids == ["seg_001", "seg_002"]
        assert sp.section_context == "小重山"

    def test_custom_visual_type(self):
        sp = ScenePlan(
            id="scene_001",
            visual_type="stock_image",
            visual_params={"query": "neural network", "fallback": "text_only"},
        )
        assert sp.visual_type == "stock_image"
        assert sp.visual_params["query"] == "neural network"

    def test_json_round_trip(self):
        original = ScenePlan(
            id="scene_001",
            visual_type="stock_image",
            visual_params={"query": "test"},
            segment_ids=["seg_001", "seg_002"],
            section_context="测试",
        )
        json_str = original.model_dump_json()
        restored = ScenePlan.model_validate_json(json_str)
        assert restored.id == "scene_001"
        assert restored.visual_type == "stock_image"
        assert restored.segment_ids == ["seg_001", "seg_002"]


# ========== SceneResult ==========


class TestSceneResult:
    def test_defaults(self):
        sr = SceneResult(id="scene_001")
        assert sr.segment_ids == []
        assert sr.start == 0.0
        assert sr.end == 0.0
        assert sr.visual.path == ""

    def test_with_visual(self):
        sr = SceneResult(
            id="scene_001",
            segment_ids=["seg_001"],
            start=0.0,
            end=5.5,
            visual=VisualResult(path="bg.jpg", width=1080, height=1920, source="pexels"),
        )
        assert sr.visual.path == "bg.jpg"
        assert sr.visual.source == "pexels"

    def test_json_round_trip(self):
        original = SceneResult(
            id="scene_001",
            segment_ids=["seg_001", "seg_002"],
            start=1.0,
            end=8.5,
        )
        json_str = original.model_dump_json()
        restored = SceneResult.model_validate_json(json_str)
        assert restored.id == "scene_001"
        assert restored.start == 1.0
        assert restored.end == 8.5
        assert restored.segment_ids == ["seg_001", "seg_002"]


# ========== PlanManifest with Scenes ==========


class TestPlanManifestWithScenes:
    def test_empty_scenes_default(self):
        m = PlanManifest()
        assert m.scenes == []

    def test_scenes_in_serialization(self):
        scene = ScenePlan(id="scene_001", segment_ids=["seg_001"])
        m = PlanManifest(scenes=[scene])
        json_str = m.model_dump_json()
        restored = PlanManifest.model_validate_json(json_str)
        assert len(restored.scenes) == 1
        assert restored.scenes[0].id == "scene_001"

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
        scene = SceneResult(id="scene_001", segment_ids=["seg_001"], start=0.0, end=5.0)
        m = ResultManifest(scenes=[scene])
        json_str = m.model_dump_json()
        restored = ResultManifest.model_validate_json(json_str)
        assert len(restored.scenes) == 1
        assert restored.scenes[0].start == 0.0

    def test_backward_compat_no_scenes_field(self):
        old_json = '{"segments": []}'
        m = ResultManifest.model_validate_json(old_json)
        assert m.scenes == []

    def test_write_then_read_preserves_scenes(self, tmp_path):
        """模拟 pipeline 写盘后读回，scenes 字段不能丢。"""
        scene = SceneResult(
            id="scene_001", segment_ids=["seg_001", "seg_002"],
            start=0.0, end=9.0,
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
        assert restored.scenes[0].segment_ids == ["seg_001", "seg_002"]
        assert restored.scenes[0].end == 9.0
