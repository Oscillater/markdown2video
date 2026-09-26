"""构建期文本溢出闸门（P0 demo 整改）。

「看似有效但内容被裁」正是契约该拦的：引擎画的字（标题卡 / section
header / 静默段正文）估算放不下目标 region 时，构建期就报错，而不是渲完
发现字被裁。与 A5 几何闸门同族——region vs region 之外的 region vs 内容。

估算模型（保守方向 = 宁可误报不可漏报）：

- 字宽：CJK/全角按 1.0×字号，ASCII 按 0.55×字号（雅黑半角实测约 0.5~0.6，
  取上沿仍偏短 → 估算行数偏多 → 偏保守）。
- 折行：按 region 可用宽度逐 token 累计（ASCII 词不拆，与字幕侧同思路）。
- 行高：字号 × 1.5（与 Remotion `SegmentedText` lineHeight 一致；manim
  实际行高略小 → 估算偏大 → 偏保守）。

两级裁决（判定行量化，估算误差要跨整一行才翻转判决，边界天然被吃掉）：

- 所需 ≤ 容量                → 通过
- 容量 < 所需 ≤ 容量 + 1 行   → warning（贴边，可能估算噪声；记入 warnings）
- 所需 > 容量 + 1 行          → error（差一整行以上，不可能是估算噪声）

渲染前执行（挂在 pipeline plan 校验阶段），失败代价是改 plan 重跑几秒，
不浪费渲染。范围只覆盖**引擎画的字**：组件内部排版归 check-component
黄金帧验收（A8 边界），不在此闸门。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, List

# 与 Md2Video.tsx SegmentedText 的 lineHeight 对齐
LINE_HEIGHT_RATIO = 1.5
# ASCII 字宽系数（雅黑半角实测 0.5~0.6，取上沿：偏保守）
ASCII_WIDTH_RATIO = 0.55

# ASCII 词/数字/路径 token（不从词中间折行，与 subtitles._tokenize 同思路）
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-/+@#%]*|\s+|.")

# 裁决级别
LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"


@dataclass(frozen=True)
class TextFitResult:
    """一次文本-区域配容量判定。"""

    region: str
    text: str
    needed_lines: int
    capacity_lines: int
    font_size: int
    level: str

    @property
    def message(self) -> str:
        return (
            f"text overflows region {self.region!r}: needs "
            f"{self.needed_lines} line(s) at {self.font_size}px, capacity "
            f"{self.capacity_lines} line(s)"
        )


def estimate_wrapped_lines(text: str, font_size: int, box_width: int) -> int:
    """估算文本按 box 宽度折行后的行数（0 宽文本 = 0 行）。

    逐 token 累计像素宽：CJK 1.0×字号、ASCII 0.55×字号；ASCII 词整体
    进行不拆。空文本返回 0；单个超宽 token 独占一行（不低于 1 行）。
    """
    stripped = str(text).strip()
    if not stripped or box_width <= 0 or font_size <= 0:
        return 0

    lines = 1
    used = 0.0
    for token in _TOKEN_RE.findall(stripped):
        if token.isspace():
            # 行首空格不占宽；行中空格算宽度但可作为折行点
            if used == 0:
                continue
            width = font_size * ASCII_WIDTH_RATIO
        elif token.isascii():
            width = len(token) * font_size * ASCII_WIDTH_RATIO
        else:
            width = len(token) * float(font_size)
        if used + width > box_width and used > 0:
            lines += 1
            used = 0.0
            if token.isspace():
                continue
        used += width
    return lines


def check_text_fit(
    text: str,
    font_size: int,
    box_width: int,
    box_height: int,
    region: str,
    *,
    line_height_ratio: float = LINE_HEIGHT_RATIO,
) -> TextFitResult:
    """文本 vs 区域容量判定（纯函数）。

    容量按整行 floor（放不下一行完整行高就没位置）；差 ≤1 行判 warn，
    超 1 行判 error。返回 TextFitResult，level 见 LEVEL_*。
    """
    line_height = font_size * line_height_ratio
    capacity_lines = max(0, int(box_height // line_height)) if line_height > 0 else 0
    needed_lines = estimate_wrapped_lines(text, font_size, box_width)

    if needed_lines <= capacity_lines:
        level = LEVEL_OK
    elif needed_lines <= capacity_lines + 1:
        level = LEVEL_WARN
    else:
        level = LEVEL_ERROR
    return TextFitResult(
        region=region,
        text=str(text),
        needed_lines=needed_lines,
        capacity_lines=capacity_lines,
        font_size=font_size,
        level=level,
    )


def classify_overflow(
    needed_px: float,
    capacity_px: float,
    line_height_px: float,
) -> str:
    """像素级两级裁决：超出 ≤1 行高 → warn，>1 行高 → error（纯分类）。

    标题卡这类"整块"（主 + 副 + 装饰条）不适合逐行数，直接用像素差
    除以行高判断超出几个行高。"""
    if needed_px <= capacity_px:
        return LEVEL_OK
    if line_height_px <= 0:
        return LEVEL_ERROR
    return LEVEL_WARN if (needed_px - capacity_px) <= line_height_px else LEVEL_ERROR


def check_texts_fit(
    items: Iterable[tuple[str, str, int, int, int]],
) -> List[TextFitResult]:
    """批量判定：items = (region_name, text, font_size, box_w, box_h)。

    一次给出全部结果（A5 模式：一次报全部，不挤牙膏）。
    """
    return [
        check_text_fit(text, font_size, box_width, box_height, region)
        for region, text, font_size, box_width, box_height in items
    ]
