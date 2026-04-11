"""Adapter Protocol — 桥接 Tool 契约与执行方式。"""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


class ExecutionMode:
    IN_PROCESS = "in_process"
    CLI = "cli"
    HTTP = "http"


@runtime_checkable
class Adapter(Protocol):
    """适配器协议：决定如何调用 Tool。"""

    @property
    def execution_mode(self) -> str:
        ...

    def invoke(self, tool: "Tool", input_data: Dict[str, Any]) -> Dict[str, Any]:
        ...
