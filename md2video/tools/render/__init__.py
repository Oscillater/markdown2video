"""Render tools 包。

manim_tool 等重实现模块按需导入（module __getattr__ 惰性导出），
避免包初始化即拉起 manim 相关依赖链（timeline 闸门等轻量模块会
导入本包内的纯 helper 子模块）。
"""
from __future__ import annotations

from typing import Any

_LAZY_EXPORTS = {
    "ManimRenderTool": "md2video.tools.render.manim_tool",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, name)
