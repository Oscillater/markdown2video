"""Style 子系统：ThemeTokens 声明 + 每引擎一个 Realizer。

包（pack）是纯数据宣言（palette/typography/motion/motif 槽位），不含引擎
代码；引擎与包正交，能力按名字引用，不认识的槽位优雅降级 + warning。
本包的顶层导出保持无 manim 依赖；引擎侧翻译官在
`md2video.style.manim_realizer` 与 `md2video.style.motifs`（按需导入）。
"""
from md2video.style.packs import DEFAULT_PACK_NAME, ThemeTokens, get_pack, register_pack
from md2video.style.schema import (
    MotionTokens,
    MotifTokens,
    PaletteTokens,
    SilentPaceTokens,
    TypographyTokens,
)

__all__ = [
    "DEFAULT_PACK_NAME",
    "MotionTokens",
    "MotifTokens",
    "PaletteTokens",
    "SilentPaceTokens",
    "ThemeTokens",
    "TypographyTokens",
    "get_pack",
    "register_pack",
]
