"""ThemeTokens schema — 设计包的纯数据宣言。

四本账里的 pack 账：风格与节奏的单一事实源。用户 DIY = 直接改包
（Hugo/Hexo 模板模型），不存在多来源自动合并。本模块只定义数据形状，
不含任何引擎代码；引擎侧换算（token → manim 参数）只在各引擎的
Realizer 里做。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _validate_hex_color(value: str) -> str:
    if not isinstance(value, str) or not _HEX_COLOR.match(value):
        raise ValueError(f"color must be a #RGB or #RRGGBB hex string, got {value!r}")
    return value


class PaletteTokens(BaseModel):
    """调色板：底/字/次级/强调色（hex）。"""

    model_config = ConfigDict(extra="forbid")

    background: str
    text: str
    secondary: str
    accent: str

    @field_validator("background", "text", "secondary", "accent")
    @classmethod
    def _hex(cls, value: str) -> str:
        return _validate_hex_color(value)


class TypographyTokens(BaseModel):
    """排印：字族 + 角色字号。

    字号用归一化单位：相对画面高度的比例（0-1）。归一化 → 引擎字号
    （manim font_size）的换算只允许存在于 ManimRealizer。
    """

    model_config = ConfigDict(extra="forbid")

    font_family: str
    size_title_main: float = Field(gt=0.0, le=1.0)
    size_title_sub: float = Field(gt=0.0, le=1.0)
    size_section_header: float = Field(gt=0.0, le=1.0)
    size_section_header_detail: float = Field(gt=0.0, le=1.0)
    size_body: float = Field(gt=0.0, le=1.0)


class SilentPaceTokens(BaseModel):
    """静默段节奏：这一类内容默认停几秒（风格问题，归 pack）。

    段时长裁决唯一：音频事实 > hold cue（未来入口）> 本节奏默认。
    """

    model_config = ConfigDict(extra="forbid")

    title_hold: float = Field(ge=0.0)
    section_header: float = Field(ge=0.0)
    body: float = Field(ge=0.0)


class MotionTokens(BaseModel):
    """动效：意图级声明（write/fade/appear/instant…），不做精确规格。

    引擎声明自己支持的意图名；不认识的意图降级为静默出现/移除 + warning。
    """

    model_config = ConfigDict(extra="forbid")

    title_reveal: str
    section_reveal: str
    body_reveal: str
    body_dismiss: str
    section_dismiss: str
    motif_transition_duration: float = Field(ge=0.0)
    silent: SilentPaceTokens


class MotifTokens(BaseModel):
    """母题槽位：可换、可无（kind 为空）、可自定义（引擎注册新 kind）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = ""


class ThemeTokens(BaseModel):
    """设计包 token：palette + typography + motion + motif。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    palette: PaletteTokens
    typography: TypographyTokens
    motion: MotionTokens
    motif: MotifTokens = Field(default_factory=MotifTokens)
