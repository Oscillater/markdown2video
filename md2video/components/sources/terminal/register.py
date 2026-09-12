"""terminal@1.0.0 表现组件注册模块（A8 首批）。

正式入库走验收入口::

    python -m md2video.check_component md2video.components.sources.terminal.register
"""
from pathlib import Path

from md2video.components.registry import register_component

register_component(
    "terminal",
    "1.0.0",
    "body",
    Path(__file__).parent / "terminal.tsx",
)
