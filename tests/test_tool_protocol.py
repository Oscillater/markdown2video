"""Tool Protocol + Adapter 单元测试。"""
from unittest.mock import MagicMock

import pytest

from md2video.tools.protocol import Tool
from md2video.tools.adapter import Adapter, ExecutionMode
from md2video.tools.adapter_impl import InProcessAdapter, CliAdapter, HttpAdapter


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


class TestAdapterProtocol:
    """验证 Adapter Protocol。"""

    def test_valid_adapter_satisfies_protocol(self):
        adapter = MagicMock()
        adapter.execution_mode = "in_process"
        adapter.invoke = lambda t, d: d
        assert isinstance(adapter, Adapter)

    def test_missing_invoke_fails(self):
        adapter = MagicMock(spec=[])
        adapter.execution_mode = "cli"
        assert not isinstance(adapter, Adapter)


class TestExecutionMode:
    def test_constants(self):
        assert ExecutionMode.IN_PROCESS == "in_process"
        assert ExecutionMode.CLI == "cli"
        assert ExecutionMode.HTTP == "http"


class TestInProcessAdapter:
    def test_invoke_delegates_to_execute(self):
        adapter = InProcessAdapter()
        tool = MagicMock()
        tool.execute.return_value = {"result": "ok"}
        assert adapter.invoke(tool, {"input": 1}) == {"result": "ok"}
        tool.execute.assert_called_once_with({"input": 1})

    def test_execution_mode(self):
        assert InProcessAdapter().execution_mode == "in_process"


class TestCliAdapter:
    def test_init(self):
        adapter = CliAdapter(command=["echo", "hello"], timeout=60)
        assert adapter.command == ["echo", "hello"]
        assert adapter.timeout == 60
        assert adapter.execution_mode == "cli"


class TestHttpAdapter:
    def test_init(self):
        adapter = HttpAdapter(url="http://localhost:8080/render")
        assert adapter.url == "http://localhost:8080/render"
        assert adapter.execution_mode == "http"
        assert adapter.timeout == 60
