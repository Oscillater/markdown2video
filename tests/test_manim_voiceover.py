"""Cached narration must consume ledger timing, not probe the media again."""
from __future__ import annotations

import pytest

from md2video.manifest.schema import AudioResult, ResultManifest, SegmentResult
from md2video.tools.render.cached_voice import CachedVoiceService


class FakeScene:
    def __init__(self):
        self.time = 4.0
        self.sounds = []
        self.waits = []

    def add_sound(self, path):
        self.sounds.append(path)

    def safe_wait(self, duration):
        if duration > 0:
            self.waits.append(duration)
            self.time += duration


def service(tmp_path, duration=2.0):
    # Deliberately not decodable: timing belongs to ExecutionAssets, not this reader.
    audio = tmp_path / "legacy-mp3.wav"
    audio.write_bytes(b"ID3cached-audio")
    manifest = ResultManifest(segments=[
        SegmentResult(id="body", audio=AudioResult(path=str(audio), duration=duration)),
    ])
    return CachedVoiceService(manifest), audio


def test_cached_audio_carries_duration_fact(tmp_path):
    svc, audio = service(tmp_path)
    with svc.use_segment("body"):
        data = svc._wrap_generate_from_text("body")
    assert data["duration"] == 2.0
    assert data["final_audio"] == str(audio)


@pytest.mark.parametrize("animation_time, remaining", [(0.5, 1.5), (2.0, 0.0), (3.0, 0.0)])
def test_voiceover_waits_only_for_remaining_audio(tmp_path, animation_time, remaining):
    svc, audio = service(tmp_path)
    scene = FakeScene()
    with svc.voiceover(scene, "body", "body") as tracker:
        assert tracker.duration == 2.0
        scene.time += animation_time
        assert tracker.get_remaining_duration() == pytest.approx(remaining)
    assert scene.time == pytest.approx(4.0 + max(2.0, animation_time))
    assert scene.sounds == [str(audio)]
    assert scene.waits == ([remaining] if remaining else [])


def test_voiceover_restores_segment_binding_after_failure(tmp_path):
    svc, _ = service(tmp_path)
    scene = FakeScene()
    with pytest.raises(ValueError, match="render failed"):
        with svc.voiceover(scene, "body", "body"):
            raise ValueError("render failed")
    assert svc._current_segment_id is None


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_audio_fact_is_rejected(tmp_path, duration):
    svc, _ = service(tmp_path, duration)
    with svc.use_segment("body"):
        with pytest.raises(ValueError, match="duration"):
            svc._wrap_generate_from_text("body")
