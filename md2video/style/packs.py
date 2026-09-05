"""设计包注册表：v0 代码内置注册，外部文件加载走 register_pack 接口。

reference pack `ink_night` 是现有 house style（黑底白字仿宋 + 圆点母题 +
现节奏常量）的纯数据抽取——只有宣言，没有引擎代码。包与社区包零特权差别。
"""
from __future__ import annotations

from md2video.style.schema import (
    MotionTokens,
    MotifTokens,
    PaletteTokens,
    SilentPaceTokens,
    ThemeTokens,
    TypographyTokens,
)

DEFAULT_PACK_NAME = "ink_night"

# manim.cfg 参考渲染分辨率（竖屏 480x854）。归一化字号按该高度标定，
# ManimRealizer 用 frame_height_px 换算回引擎 font_size。
_REFERENCE_FRAME_HEIGHT_PX = 854

_PACKS: dict[str, ThemeTokens] = {}


def ink_night() -> ThemeTokens:
    """Reference pack：现有 house style 的纯数据宣言。

    字号注释为标定值（参考分辨率 854px 高下的 manim font_size）。
    accent #58C4DD 是 manim `BLUE`（母题第二圆点色）。
    """
    return ThemeTokens(
        id="ink_night",
        palette=PaletteTokens(
            background="#000000",
            text="#FFFFFF",
            secondary="#FFFFFF",
            accent="#58C4DD",
        ),
        typography=TypographyTokens(
            font_family="FZShuSong-Z01S",
            size_title_main=40 / _REFERENCE_FRAME_HEIGHT_PX,
            size_title_sub=30 / _REFERENCE_FRAME_HEIGHT_PX,
            size_section_header=20 / _REFERENCE_FRAME_HEIGHT_PX,
            size_section_header_detail=12 / _REFERENCE_FRAME_HEIGHT_PX,
            size_body=15 / _REFERENCE_FRAME_HEIGHT_PX,
        ),
        motion=MotionTokens(
            title_reveal="write",
            section_reveal="write",
            body_reveal="appear",
            body_dismiss="instant",
            section_dismiss="fade",
            motif_transition_duration=1.0,
            silent=SilentPaceTokens(
                title_hold=1.0,
                section_header=0.5,
                body=2.0,
            ),
        ),
        motif=MotifTokens(kind="orbit_dots"),
    )


def register_pack(tokens: ThemeTokens) -> None:
    """注册一个设计包；重复注册同一 id 视为配置错误（fail fast）。"""
    if tokens.id in _PACKS:
        raise ValueError(f"Style pack already registered: {tokens.id}")
    _PACKS[tokens.id] = tokens


def get_pack(name: str | None = None) -> ThemeTokens:
    """按名字取包；未知名降级到默认包并告警（引擎不认识就降级 + warning）。"""
    resolved = name or DEFAULT_PACK_NAME
    pack = _PACKS.get(resolved)
    if pack is None:
        print(
            f"  Style warning: unknown style pack {resolved!r}; "
            f"falling back to {DEFAULT_PACK_NAME!r}"
        )
        return _PACKS[DEFAULT_PACK_NAME]
    return pack


def pack_names() -> list[str]:
    return sorted(_PACKS)


register_pack(ink_night())
