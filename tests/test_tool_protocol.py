"""Tool Protocol 单元测试。"""
from unittest.mock import MagicMock

from md2video.tools.protocol import Tool


class TestToolProtocol:
    """验证 Tool Protocol 的 isinstance 检查和基本行为。"""

    def test_valid_tool_satisfies_protocol(self):
        """实现了 tool_type、provider_name、execute 的类满足 Protocol。"""
        tool = MagicMock()
        tool.tool_type = "tts"
        tool.provider_name = "edge-tts"
        tool.execute = lambda d: d
        assert isinstance(tool, Tool)

    def test_missing_tool_type_fails(self):
        tool = MagicMock(spec=[])
        tool.provider_name = "x"
        tool.execute = lambda d: d
        assert not isinstance(tool, Tool)

    def test_missing_execute_fails(self):
        tool = MagicMock(spec=[])
        tool.tool_type = "tts"
        tool.provider_name = "x"
        assert not isinstance(tool, Tool)
