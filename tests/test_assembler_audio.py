"""Regression checks for short/silent audio assembly and explicit gain."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import md2video.assembler.ffmpeg_assembler as assembler


@pytest.mark.parametrize("gain", [0.0, 0.5, 2.0])
@pytest.mark.parametrize("has_audio", [False, True])
@pytest.mark.parametrize("has_music", [False, True])
def test_explicit_gain_is_used_on_all_audio_paths(monkeypatch, gain, has_audio, has_music):
    commands = []
    monkeypatch.setattr(assembler, "run", lambda command: commands.append(command))
    music = [{"path": Path("bgm.wav"), "start": 0.0}] if has_music else []
    assembler.build_and_run_ffmpeg(Path("base.mp4"), music, [], has_audio, Path("out.mp4"), 5.0, 128, 128, gain=gain)
    filters = commands[0][commands[0].index("-filter_complex") + 1]
    assert f"volume={gain}" in filters
    assert "loudnorm" not in filters


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs FFmpeg and ffprobe")
@pytest.mark.parametrize("has_audio", [False, True])
def test_short_silent_clip_can_be_assembled(tmp_path, has_audio):
    base = tmp_path / "base.mp4"
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:r=30:d=0.5"]
    if has_audio:
        command += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    command += ["-t", "0.5", "-c:v", "libx264", "-c:a", "aac", str(base)]
    subprocess.run(command, capture_output=True, check=True)
    out = tmp_path / "out.mp4"
    assembler.build_and_run_ffmpeg(base, [], [], has_audio, out, 0.5, 128, 128)
    assert out.stat().st_size > 0
    assert assembler.ffprobe_duration(out) == pytest.approx(0.5, abs=0.1)
    assert assembler.has_audio_stream(out)
