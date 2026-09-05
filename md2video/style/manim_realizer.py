"""ManimRealizer — token → Manim 引擎参数的唯一换算点。

宣言只有一份，翻译官每个引擎一个。pack 写意图名（write/fade/appear…、
orbit_dots），本类负责把它们翻译成 manim 动画、颜色、字号；引擎不认识
的意图名降级为静默出现/移除并告警。归一化字号 → manim font_size 的换算
只允许存在这里。
"""
from __future__ import annotations

from typing import Any

from manim import Animation, FadeIn, FadeOut, Text, Write

from md2video.style.schema import ThemeTokens

# 排印角色 → TypographyTokens 字段
_TYPOGRAPHY_SIZE_FIELDS = {
    "title_main": "size_title_main",
    "title_sub": "size_title_sub",
    "section_header": "size_section_header",
    "section_header_detail": "size_section_header_detail",
    "body": "size_body",
}

REVEAL_INTENTS = ("write", "fade", "appear")
DISMISS_INTENTS = ("instant", "fade")


class ManimRealizer:
    """把一份 ThemeTokens 翻译成 manim 文本对象、动画与节奏。"""

    def __init__(self, tokens: ThemeTokens, frame_height_px: int):
        if frame_height_px <= 0:
            raise ValueError(f"frame_height_px must be positive, got {frame_height_px}")
        self.tokens = tokens
        self.frame_height_px = frame_height_px
        self.warnings: list[str] = []
        self._warned_intents: set[str] = set()

    # ---- 排印 ----

    def font_family(self) -> str:
        return self.tokens.typography.font_family

    def font_size(self, role: str) -> int:
        """归一化字号 → manim font_size（相对画面高 × 参考像素高）。"""
        field = _TYPOGRAPHY_SIZE_FIELDS.get(role)
        if field is None:
            raise ValueError(f"Unknown typography role: {role}")
        fraction = getattr(self.tokens.typography, field)
        return max(1, round(fraction * self.frame_height_px))

    def text(self, content: str, *, role: str, **kwargs: Any) -> Text:
        """按角色构建 Text：字族/颜色/字号全部来自 token。"""
        return Text(
            content,
            font=self.font_family(),
            color=self.tokens.palette.text,
            font_size=self.font_size(role),
            **kwargs,
        )

    # ---- 颜色 ----

    def background_color(self) -> str:
        return self.tokens.palette.background

    def motif_colors(self) -> tuple[str, str]:
        """母题双色：主点=文字色，副点=强调色。"""
        return (self.tokens.palette.text, self.tokens.palette.accent)

    # ---- 动效意图 ----

    def reveal(self, intent: str, mobject: Any) -> Animation | None:
        """出现意图 → manim 动画；None 表示静默出现（self.add）。"""
        if intent == "write":
            return Write(mobject)
        if intent == "fade":
            return FadeIn(mobject)
        if intent == "appear":
            return None
        self._warn_unknown_intent("reveal", intent)
        return None

    def dismiss(self, intent: str, mobject: Any) -> Animation | None:
        """移除意图 → manim 动画；None 表示静默移除（self.remove）。"""
        if intent == "instant":
            return None
        if intent == "fade":
            return FadeOut(mobject)
        self._warn_unknown_intent("dismiss", intent)
        return None

    def _warn_unknown_intent(self, kind: str, intent: str) -> None:
        key = f"{kind}:{intent}"
        if key in self._warned_intents:
            return
        self._warned_intents.add(key)
        warning = (
            f"Unknown {kind} intent {intent!r}; degrading to silent "
            f"appear/remove (pack/engine capability mismatch)"
        )
        self.warnings.append(warning)
        print(f"  Style warning: {warning}")

    # ---- 节奏 ----

    def silent_pace(self, slot: str) -> float:
        """静默段节奏：'title_hold' | 'section_header' | 'body'。"""
        if not hasattr(self.tokens.motion.silent, slot):
            raise ValueError(f"Unknown silent pace slot: {slot}")
        return getattr(self.tokens.motion.silent, slot)

    def transition_duration(self) -> float:
        return self.tokens.motion.motif_transition_duration
