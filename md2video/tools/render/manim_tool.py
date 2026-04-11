"""ManimRenderTool — Tool Protocol 包装，实际逻辑在 Pipeline 中通过 CLI 适配器调用。"""
from __future__ import annotations

from typing import Any, Dict


class ManimRenderTool:
    """批量渲染工具 (text_only scenes)。

    Phase 3: execute() 为 stub，渲染逻辑仍由 Pipeline 内的 CLI 子进程完成。
    Phase 5+: 渲染逻辑将迁移到此 execute() 中。
    """

    @property
    def tool_type(self) -> str:
        return "render"

    @property
    def provider_name(self) -> str:
        return "manim"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Manim 批量渲染 (Phase 3 由 Pipeline 直接调度)。"""
        raise NotImplementedError(
            "ManimRenderTool is dispatched via Pipeline CLI path, not direct execute()."
        )
