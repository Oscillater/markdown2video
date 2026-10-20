"""Edge TTS: cache contracts, truthful formats, rates and duration failures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from md2video.tools.tts.edge_tts import EdgeTTSTool


def _expected_cache_key(text, voice="zh-CN-YunxiNeural", speed=1.0):
    canonical = json.dumps({"speed": speed, "text": text, "voice": voice}, sort_keys=True)
    return hashlib.sha256(f"tts:{canonical}".encode()).hexdigest()


@pytest.fixture
def network(monkeypatch):
    calls = []

    class FakeCommunicate:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def save(self, path):
            Path(path).write_bytes(b"ID3test-mp3")

    monkeypatch.setattr("md2video.tools.tts.edge_tts.Communicate", FakeCommunicate)
    return calls


@pytest.fixture
def fake_wav(monkeypatch, audio_file):
    calls = []

    def convert(self, source, target):
        calls.append((source, target))
        target.write_bytes(audio_file.read_bytes())

    monkeypatch.setattr(EdgeTTSTool, "_write_wav", convert)
    return calls


@pytest.fixture
def fake_duration(monkeypatch):
    monkeypatch.setattr(EdgeTTSTool, "_get_duration", lambda self, path: 2.5)


def test_creates_cache_dir(tmp_path):
    cache = tmp_path / "cache"
    EdgeTTSTool(cache_dir=cache)
    assert cache.is_dir()


def test_cache_hit(tmp_path, audio_file, network, fake_wav, fake_duration):
    cached = tmp_path / f"{_expected_cache_key('hello')}.wav"
    cached.write_bytes(audio_file.read_bytes())
    result = EdgeTTSTool(tmp_path).synthesize("hello")
    assert result == {
        "path": str(cached), "duration": 2.5,
        "provider": "edge-tts", "cache_key": _expected_cache_key("hello"),
    }
    assert network == []
    assert fake_wav == []


def test_cache_miss(tmp_path, network, fake_wav, fake_duration):
    tool = EdgeTTSTool(tmp_path)
    first = tool.synthesize("hello")
    second = tool.synthesize("hello")
    assert first == second
    assert len(network) == len(fake_wav) == 1
    assert Path(first["path"]).read_bytes().startswith(b"RIFF")
    assert not list(tmp_path.glob(".tts-*"))


def test_custom_voice(tmp_path, network, fake_wav, fake_duration):
    result = EdgeTTSTool(tmp_path).synthesize("hello", voice="en-US-JennyNeural")
    assert result["cache_key"] == _expected_cache_key("hello", "en-US-JennyNeural")
    assert network[0]["voice"] == "en-US-JennyNeural"


@pytest.mark.parametrize("speed, rate", [(0.5, "-50%"), (0.9, "-10%"), (1.0, "+0%"), (1.1, "+10%"), (1.5, "+50%")])
def test_speed_rate(tmp_path, network, fake_wav, fake_duration, speed, rate):
    EdgeTTSTool(tmp_path).synthesize("hello", speed=speed)
    assert network[0]["rate"] == rate


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf")])
def test_invalid_speed_rejected(tmp_path, network, speed):
    with pytest.raises(ValueError, match="speed"):
        EdgeTTSTool(tmp_path).synthesize("hello", speed=speed)
    assert network == []


def test_mp3_request_keeps_mp3_bytes(tmp_path, network, fake_duration):
    result = EdgeTTSTool(tmp_path).execute({"text": "hello", "format": "mp3"})
    assert Path(result["path"]).suffix == ".mp3"
    assert Path(result["path"]).read_bytes() == b"ID3test-mp3"


def test_unknown_format_rejected(tmp_path, network):
    with pytest.raises(ValueError, match="format"):
        EdgeTTSTool(tmp_path).synthesize("hello", fmt="not-a-format")
    assert network == []


def test_legacy_mislabeled_wav_is_repaired_without_network(tmp_path, network, fake_wav, fake_duration):
    cached = tmp_path / f"{_expected_cache_key('hello')}.wav"
    cached.write_bytes(b"ID3old-mp3")
    EdgeTTSTool(tmp_path).synthesize("hello")
    assert cached.read_bytes().startswith(b"RIFF")
    assert len(fake_wav) == 1
    assert network == []


def test_failed_download_does_not_poison_cache(tmp_path, monkeypatch):
    class BrokenCommunicate:
        def __init__(self, **kwargs):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("download failed")

    monkeypatch.setattr("md2video.tools.tts.edge_tts.Communicate", BrokenCommunicate)
    with pytest.raises(RuntimeError, match="download failed"):
        EdgeTTSTool(tmp_path).synthesize("hello")
    assert list(tmp_path.iterdir()) == []


class TestGetDuration:
    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_success(self, run, tmp_path):
        run.return_value = MagicMock(returncode=0, stdout="4.2\n")
        assert EdgeTTSTool(tmp_path)._get_duration(Path("audio.wav")) == 4.2

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_failure_is_not_a_fake_duration(self, run, tmp_path):
        run.return_value = MagicMock(returncode=1, stderr="cannot decode audio")
        with pytest.raises(RuntimeError, match="ffprobe"):
            EdgeTTSTool(tmp_path)._get_duration(Path("audio.wav"))

    @pytest.mark.parametrize("output", ["not_a_number", "", "nan", "inf", "0", "-1"])
    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_invalid_duration_rejected(self, run, output, tmp_path):
        run.return_value = MagicMock(returncode=0, stdout=output)
        with pytest.raises(RuntimeError, match="duration"):
            EdgeTTSTool(tmp_path)._get_duration(Path("audio.wav"))


def test_tool_protocol(tmp_path, network, fake_wav, fake_duration):
    tool = EdgeTTSTool(tmp_path)
    assert tool.tool_type == "tts" and tool.provider_name == "edge-tts"
    result = tool.execute({"text": "hello", "speed": 1.0, "format": "wav"})
    assert result["duration"] == 2.5
    assert len(network) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs FFmpeg")
def test_real_legacy_cache_conversion(tmp_path, network):
    cached = tmp_path / f"{_expected_cache_key('hello')}.wav"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
        "-f", "mp3", str(cached),
    ], check=True, capture_output=True)
    result = EdgeTTSTool(tmp_path).synthesize("hello")
    assert cached.read_bytes()[:4] == b"RIFF"
    assert cached.read_bytes()[8:12] == b"WAVE"
    assert result["duration"] == pytest.approx(0.5, abs=0.1)
    assert network == []


@patch("md2video.tools.tts.edge_tts.subprocess.run")
def test_failed_conversion_preserves_original_cache(run, tmp_path, network):
    cached = tmp_path / f"{_expected_cache_key('hello')}.wav"
    cached.write_bytes(b"ID3original")
    run.return_value = MagicMock(returncode=1, stderr="conversion failed")
    with pytest.raises(RuntimeError, match="FFmpeg"):
        EdgeTTSTool(tmp_path).synthesize("hello")
    assert cached.read_bytes() == b"ID3original"
    assert not list(tmp_path.glob(".tts-*"))
