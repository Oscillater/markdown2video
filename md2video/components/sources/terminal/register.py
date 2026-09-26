"""terminal@1.0.0 表现组件注册模块（A8 首批）。

正式入库走验收入口::

    python -m md2video.check_component md2video.components.sources.terminal.register
"""
from pathlib import Path

from md2video.components.registry import register_component


def displayed_texts(payload: list[dict]) -> list[str]:
    """P0 字幕去重契约：terminal 把每个 content 段画成一行（原文上屏）。"""
    return [
        str(seg["text"])
        for seg in payload
        if seg.get("segment_type") == "content"
    ]


register_component(
    "terminal",
    "1.0.0",
    "body",
    Path(__file__).parent / "terminal.tsx",
    displayed_texts=displayed_texts,
    register_module=__name__,
)
