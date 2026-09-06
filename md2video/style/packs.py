"""设计包注册表：内置注册 + 外部文件加载（env `MD2VIDEO_STYLE_PACK_FILE`）。

reference pack `ink_night` 是现有 house style（黑底白字仿宋 + 圆点母题 +
现节奏常量）的纯数据抽取——只有宣言，没有引擎代码。包与社区包零特权差别。

外部文件包：`MD2VIDEO_STYLE_PACK_FILE` 指向一个 ThemeTokens JSON，在
`get_pack` 解析路径上惰性加载一次（幂等缓存，管线与渲染子进程两侧一致
——两个进程各自在第一次取包时加载）。文件解析/校验失败、缺文件、与已
注册包重名都 fail fast（用户显式指定的包坏了必须报错）；选择仍走
`MD2VIDEO_STYLE_PACK` 名字，未知名降级 + warning。本机制只管加载，不提
供第二套内置包（那是 B3）。
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError

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
    _load_pack_file_once()
    resolved = name or DEFAULT_PACK_NAME
    pack = _PACKS.get(resolved)
    if pack is None:
        print(
            f"  Style warning: unknown style pack {resolved!r}; "
            f"falling back to {DEFAULT_PACK_NAME!r}"
        )
        return _PACKS[DEFAULT_PACK_NAME]
    return pack


STYLE_PACK_ENV = "MD2VIDEO_STYLE_PACK"
STYLE_PACK_FILE_ENV = "MD2VIDEO_STYLE_PACK_FILE"

_pack_file_loaded = False


def _load_pack_file_once() -> None:
    """把 env 指向的 ThemeTokens JSON 注册进包表；进程内只加载一次（幂等）。

    显式指定的文件出任何问题（缺文件、坏 JSON、token 不合法、与已注册包
    重名）都 fail fast——用户指名要的包坏了，静默降级会掩盖配置错误。
    管线与渲染子进程两侧一致：各进程在第一次 get_pack 时加载各自 env。
    """
    global _pack_file_loaded
    if _pack_file_loaded:
        return
    _pack_file_loaded = True

    raw = os.environ.get(STYLE_PACK_FILE_ENV, "")
    if not raw.strip():
        return
    path = Path(raw.strip())
    if not path.is_file():
        raise FileNotFoundError(
            f"{STYLE_PACK_FILE_ENV} points to a missing file: {path}"
        )
    try:
        tokens = ThemeTokens.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(
            f"{STYLE_PACK_FILE_ENV} is not a valid ThemeTokens JSON ({path}): {exc}"
        ) from exc
    # 重名注册是配置错误：外部包不许静默顶掉内置/先前注册的包
    register_pack(tokens)


def active_pack() -> tuple[str, ThemeTokens]:
    """解析当前生效包，返回 (请求名, 包)。

    与渲染子进程同一规则（env `MD2VIDEO_STYLE_PACK`，缺省默认包），供
    管线侧检查（viewer 展示、降级 warning）使用；不认识的名字由
    get_pack 降级，调用方据此发 warning。
    """
    requested = os.environ.get(STYLE_PACK_ENV) or DEFAULT_PACK_NAME
    return requested, get_pack(requested)


def pack_names() -> list[str]:
    # 走一次惰性加载，让"已注册包"名单与 get_pack 解析路径一致
    _load_pack_file_once()
    return sorted(_PACKS)


def reset_pack_file_cache() -> None:
    """清掉"外部包文件已加载"标记（测试与进程级重载用）；不撤销已注册包。"""
    global _pack_file_loaded
    _pack_file_loaded = False


def reset_pack_registry() -> None:
    """恢复为仅内置包并清掉外部文件加载标记（测试与进程级重载用）。"""
    _PACKS.clear()
    register_pack(ink_night())
    reset_pack_file_cache()


register_pack(ink_night())
