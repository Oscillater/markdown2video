"""ManimRenderTool 基础测试（Protocol conformance）。"""
import pytest

from md2video.tools.protocol import Tool
from md2video.tools.render.manim_tool import ManimRenderTool


class TestManimRenderTool:
    def test_tool_type(self):
        tool = ManimRenderTool()
        assert tool.tool_type == "render"

    def test_provider_name(self):
        tool = ManimRenderTool()
        assert tool.provider_name == "manim"

    def test_satisfies_tool_protocol(self):
        tool = ManimRenderTool()
        assert isinstance(tool, Tool)

    def test_execute_raises_not_implemented(self):
        tool = ManimRenderTool()
        with pytest.raises(NotImplementedError):
            tool.execute({})
