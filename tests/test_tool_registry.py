"""ToolRegistry 单元测试。"""
from unittest.mock import MagicMock

import pytest

from md2video.tools.registry import ToolRegistry


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = MagicMock()
        tool.provider_name = "edge-tts"
        reg.register("tts", tool)
        assert reg.get_tool("tts", "edge-tts") is tool

    def test_get_unregistered_returns_none(self):
        reg = ToolRegistry()
        assert reg.get_tool("tts", "nonexistent") is None

    def test_get_unregistered_type_returns_none(self):
        reg = ToolRegistry()
        assert reg.get_tool("image", "pexels") is None

    def test_has(self):
        reg = ToolRegistry()
        tool = MagicMock()
        tool.provider_name = "manim"
        reg.register("text_only", tool)
        assert reg.has("text_only", "manim") is True
        assert reg.has("text_only", "other") is False

    def test_get_providers(self):
        reg = ToolRegistry()
        t1 = MagicMock()
        t1.provider_name = "a"
        t2 = MagicMock()
        t2.provider_name = "b"
        reg.register("tts", t1)
        reg.register("tts", t2)
        providers = reg.get_providers("tts")
        assert "a" in providers
        assert "b" in providers

    def test_overwrite_provider(self):
        reg = ToolRegistry()
        t1 = MagicMock()
        t1.provider_name = "x"
        t2 = MagicMock()
        t2.provider_name = "x"
        reg.register("tts", t1)
        reg.register("tts", t2)
        assert reg.get_tool("tts", "x") is t2
