"""ffprobe 解析兜底：Remotion 产出的 mp4 流信息带尾部空字段（如 480x854x），
装配器不得因此炸掉。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from md2video.assembler.ffmpeg_assembler import ffprobe_resolution


class _FakeProc:
    def __init__(self, stdout: str):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def test_ffprobe_resolution_tolerates_trailing_empty_field():
    with patch("subprocess.run", return_value=_FakeProc("480x854x\n")):
        assert ffprobe_resolution(Path("fake.mp4")) == (480, 854)


def test_ffprobe_resolution_plain_output():
    with patch("subprocess.run", return_value=_FakeProc("1920x1080\n")):
        assert ffprobe_resolution(Path("fake.mp4")) == (1920, 1080)
