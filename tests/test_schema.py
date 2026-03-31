"""Tests for md2video.manifest.schema Pydantic models."""
from __future__ import annotations

import json

from md2video.manifest.schema import (
    AudioRequest,
    AudioResult,
    PlanManifest,
    ResultManifest,
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
