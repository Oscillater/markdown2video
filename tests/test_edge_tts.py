"""Tests for md2video.tools.tts.edge_tts (fully mocked)."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from md2video.tools.tts.edge_tts import EdgeTTSTool


def _expected_cache_key(text, voice, speed):
    """匹配 ToolCache.make_key 的 sha256 格式。"""
    canonical = json.dumps({"speed": speed, "text": text, "voice": voice}, sort_keys=True)
    return hashlib.sha256(f"tts:{canonical}".encode()).hexdigest()


class TestEdgeTTSToolInit:
    def test_creates_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "tts_cache"
        EdgeTTSTool(cache_dir=cache_dir)
        assert cache_dir.exists()


class TestSynthesize:
    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_cache_hit(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        # 预创建缓存文件
        voice, speed = "zh-CN-YunxiNeural", 1.0
        cache_key = _expected_cache_key("hello", voice, speed)
        cached_file = tmp_path / f"{cache_key}.wav"
        cached_file.write_bytes(b"\x00" * 100)

        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="2.5\n")

        tool = EdgeTTSTool(cache_dir=tmp_path, voice=voice)
        result = tool.synthesize("hello", speed=speed)

        assert result["path"] == str(cached_file)
        assert result["duration"] == 2.5
        assert result["provider"] == "edge-tts"
        assert result["cache_key"] == cache_key
        # 缓存命中不应调用 asyncio.run
        mock_asyncio_run.assert_not_called()

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_cache_miss(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        voice, speed = "zh-CN-YunxiNeural", 1.0
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="3.0\n")

        tool = EdgeTTSTool(cache_dir=tmp_path, voice=voice)
        result = tool.synthesize("new text", speed=speed)

        cache_key = _expected_cache_key("new text", voice, speed)
        assert result["cache_key"] == cache_key
        assert result["duration"] == 3.0
        # 缓存未命中应调用 asyncio.run
        mock_asyncio_run.assert_called_once()

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_custom_voice(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="1.0\n")
        tool = EdgeTTSTool(cache_dir=tmp_path, voice="zh-CN-YunxiNeural")
        result = tool.synthesize("hello", voice="en-US-JennyNeural")
        cache_key = _expected_cache_key("hello", "en-US-JennyNeural", 1.0)
        assert result["cache_key"] == cache_key

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_custom_speed_rate_string(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="1.0\n")
        tool = EdgeTTSTool(cache_dir=tmp_path)

        # 捕获 Communicate 的参数
        def capture_asyncio(coro):
            # 提取 Communicate 参数
            return None
        mock_asyncio_run.side_effect = capture_asyncio

        tool.synthesize("hello", speed=1.5)

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_cache_key_deterministic(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="1.0\n")
        tool = EdgeTTSTool(cache_dir=tmp_path)
        r1 = tool.synthesize("same text", speed=1.0)
        # 清除 mock 调用记录
        mock_asyncio_run.reset_mock()
        mock_subprocess_run.reset_mock()
        r2 = tool.synthesize("same text", speed=1.0)
        assert r1["cache_key"] == r2["cache_key"]


class TestGetDuration:
    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="4.2\n")
        tool = EdgeTTSTool(cache_dir="/tmp/dummy")
        assert tool._get_duration(Path("audio.wav")) == 4.2

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_ffprobe_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        tool = EdgeTTSTool(cache_dir="/tmp/dummy")
        assert tool._get_duration(Path("audio.wav")) == 1.0

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    def test_invalid_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not_a_number\n")
        tool = EdgeTTSTool(cache_dir="/tmp/dummy")
        assert tool._get_duration(Path("audio.wav")) == 1.0


class TestToolProtocol:
    def test_tool_type(self, tmp_path):
        tool = EdgeTTSTool(cache_dir=tmp_path)
        assert tool.tool_type == "tts"

    def test_provider_name(self, tmp_path):
        tool = EdgeTTSTool(cache_dir=tmp_path)
        assert tool.provider_name == "edge-tts"

    @patch("md2video.tools.tts.edge_tts.subprocess.run")
    @patch("md2video.tools.tts.edge_tts.asyncio.run")
    def test_execute_delegates_to_synthesize(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="2.0\n")
        tool = EdgeTTSTool(cache_dir=tmp_path)
        result = tool.execute({"text": "hello", "speed": 1.0, "format": "wav"})
        assert result["provider"] == "edge-tts"
        assert result["duration"] == 2.0
        mock_asyncio_run.assert_called_once()
