"""Tool Protocol — 统一工具接口定义。
Tool 只定义 JSON 输入/输出契约，不绑定执行方式（进程内/CLI/HTTP）。
"""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """工具协议：所有工具必须实现 tool_type、provider_name 和 execute()。"""

    @property
    def tool_type(self) -> str:
        """工具类别: 'tts' | 'image' | 'video' | 'render'。"""
        ...

    @property
    def provider_name(self) -> str:
        """Provider 标识: 'edge-tts' | 'manim' | 'pexels' | ...。"""
        ...

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具，接收结构化 dict 输入，返回结构化 dict 输出。"""
        ...
