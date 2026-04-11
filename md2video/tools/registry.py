"""ToolRegistry — visual_type + provider_name → Tool 实例的映射。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class ToolRegistry:
    """工具注册表。"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}  # visual_type -> {provider: Tool}

    def register(self, visual_type: str, tool: Any) -> None:
        """注册工具实现。"""
        if visual_type not in self._tools:
            self._tools[visual_type] = {}
        self._tools[visual_type][tool.provider_name] = tool

    def get_tool(self, visual_type: str, provider_name: str) -> Optional[Any]:
        """按 visual_type + provider 获取工具。"""
        return self._tools.get(visual_type, {}).get(provider_name)

    def get_providers(self, visual_type: str) -> List[str]:
        """列出 visual_type 下已注册的 provider。"""
        return list(self._tools.get(visual_type, {}).keys())

    def has(self, visual_type: str, provider_name: str) -> bool:
        return provider_name in self._tools.get(visual_type, {})
