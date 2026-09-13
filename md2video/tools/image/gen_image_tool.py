"""GenImageTool — 程序化插画生成（代码生图，provider="procedural"）。

知识区格式的图片供给 v1：不接外部 API，用 PIL 按参数确定性绘制抽象插画
（概念图/分层图/波形/结构块四种母题）。同一份 prompt+参数永远产出逐字节
相同的 PNG——确定性使缓存命中即可复用，也让成片可复现性不受影响（生图
在「素材事实」侧，不在渲染契约侧）。

图内不渲染任何文字：知识区格式里文字归字幕与解说，插画只负责画面。
未来 text2image（AI 生图）注册到同一 visual_type `gen_image` 下作为另一个
provider，引用方式与 stock_image 完全同构（scene `visual_type` +
`visual_params` → 装配层按 timeline 叠加）。
"""
from __future__ import annotations

import hashlib
import io
import math
import random
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageDraw

from md2video.tools.cache import ToolCache

# 插画母题词汇表；visual_params.style 必须取自这里（拼错 fail fast，
# 走管线既有的「工具失败 → warning + 降级」通道，不静默换图）
STYLES = ("orbit", "layers", "waves", "blocks")

# 深底调色板族（与 ink_night 视频气质同源）；visual_params.palette 可选其一
PALETTES: dict[str, dict[str, str]] = {
    "ink": {"bg": "#0B0E14", "primary": "#4FC3F7", "secondary": "#FFB86C", "dim": "#1A2230"},
    "moss": {"bg": "#0E1410", "primary": "#9DE37D", "secondary": "#3DDC97", "dim": "#1A241C"},
    "dusk": {"bg": "#12101A", "primary": "#C792EA", "secondary": "#FF7A9E", "dim": "#221E30"},
}

# 默认 9:16 双倍分辨率（竖屏 480x854 的 2 倍），给 Ken Burns 留推近余量
_DEFAULT_WIDTH = 960
_DEFAULT_HEIGHT = 1704
_MIN_SIZE = 64
_MAX_SIZE = 4096


class GenImageTool:
    """程序化插画工具：prompt+参数 → 确定性 PNG（缓存于 ToolCache）。"""

    def __init__(self, cache_dir: str | Path = "artifacts/cache/images"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = ToolCache(self.cache_dir)

    # --- Tool Protocol conformance ---

    @property
    def tool_type(self) -> str:
        return "image"

    @property
    def provider_name(self) -> str:
        return "procedural"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tool Protocol: visual tool 输入 → 输出契约。"""
        shot_id = input_data["shot"]["id"]
        visual_params = input_data["scene"].get("visual_params", {})
        prompt = str(visual_params.get("prompt", ""))
        if not prompt.strip():
            raise ValueError("GenImageTool requires visual_params.prompt")

        style = str(visual_params.get("style", ""))
        if style and style not in STYLES:
            raise ValueError(
                f"Unknown gen_image style {style!r}; available: {STYLES}"
            )
        palette = str(visual_params.get("palette", ""))
        if palette and palette not in PALETTES:
            raise ValueError(
                f"Unknown gen_image palette {palette!r}; available: {sorted(PALETTES)}"
            )
        width = int(visual_params.get("width", _DEFAULT_WIDTH))
        height = int(visual_params.get("height", _DEFAULT_HEIGHT))

        result = self.generate(
            prompt, style=style, palette=palette, width=width, height=height,
        )
        result["shot_id"] = shot_id
        return {"visuals": [result]}

    # --- Core logic ---

    def generate(
        self,
        prompt: str,
        style: str = "",
        palette: str = "",
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
    ) -> Dict[str, Any]:
        """生成（或命中缓存）一张插画，返回 visual result dict。"""
        width = max(_MIN_SIZE, min(_MAX_SIZE, int(width)))
        height = max(_MIN_SIZE, min(_MAX_SIZE, int(height)))
        seed = _seed_from(prompt)
        if not style:
            style = STYLES[seed % len(STYLES)]
        if not palette:
            palette = sorted(PALETTES)[seed % len(sorted(PALETTES))]

        cache_params = {
            "prompt": prompt,
            "style": style,
            "palette": palette,
            "width": width,
            "height": height,
            "generator": "procedural.v2",
        }
        cache_key = self._cache.make_key("image", cache_params)

        meta = self._cache.read_json("image", cache_key + "_meta")
        img_path = self._cache.cache_path("image", cache_key, ext="png")
        if meta and img_path.exists():
            return {
                "path": str(img_path),
                "width": meta["width"],
                "height": meta["height"],
                "source": "procedural",
                "style": style,
                "cache_key": cache_key,
                "duration": 0.0,
            }

        image = _draw(style, PALETTES[palette], seed, width, height)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self._cache.write("image", cache_key, buffer.getvalue(), ext="png")
        self._cache.write_json("image", cache_key + "_meta", {
            "width": width,
            "height": height,
            "style": style,
            "palette": palette,
        })

        return {
            "path": str(img_path),
            "width": width,
            "height": height,
            "source": "procedural",
            "style": style,
            "cache_key": cache_key,
            "duration": 0.0,
        }


def _seed_from(text: str) -> int:
    """prompt → 稳定种子（跨运行、跨平台一致；不用 Python 内置 hash）。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _draw(
    style: str, colors: dict[str, str], seed: int, width: int, height: int
) -> Image.Image:
    """母题绘制入口：纯函数，(style, colors, seed, size) → PNG 画面。"""
    rng = random.Random(f"{style}:{seed}")
    image = Image.new("RGB", (width, height), colors["bg"])
    draw = ImageDraw.Draw(image)
    _draw_background_texture(draw, colors, rng, width, height)
    if style == "orbit":
        _draw_orbit(draw, colors, rng, width, height)
    elif style == "layers":
        _draw_layers(draw, colors, rng, width, height)
    elif style == "waves":
        _draw_waves(draw, colors, rng, width, height)
    else:
        _draw_blocks(draw, colors, rng, width, height)
    return image


def _draw_background_texture(
    draw: ImageDraw.ImageDraw, colors: dict[str, str], rng: random.Random,
    width: int, height: int,
) -> None:
    """稀疏底纹圆点，给纯色底一点层次（低透明度用暗色近似）。"""
    for _ in range(40):
        x = rng.randint(0, width)
        y = rng.randint(0, height)
        radius = rng.randint(2, 5)
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius), fill=colors["dim"],
        )


def _unit(size: int) -> float:
    return size / 100.0


def _draw_orbit(
    draw: ImageDraw.ImageDraw, colors: dict[str, str], rng: random.Random,
    width: int, height: int,
) -> None:
    """概念/系统图母题：中心圆 + 同心轨道 + 轨道上的节点与连线。"""
    cx, cy = width / 2, height / 2
    base = min(width, height)
    rings = rng.randint(3, 5)
    radii = [base * (0.16 + 0.11 * i) for i in range(rings)]
    nodes: list[tuple[float, float]] = []
    for index, radius in enumerate(radii):
        color = colors["primary"] if index % 2 == 0 else colors["dim"]
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            outline=color, width=max(2, int(_unit(base) * 0.6)),
        )
        angle = rng.uniform(0, math.tau)
        x = cx + math.cos(angle) * radius
        y = cy + math.sin(angle) * radius
        nodes.append((x, y))
    for (ax, ay), (bx, by) in zip(nodes, nodes[1:]):
        draw.line((ax, ay, bx, by), fill=colors["secondary"], width=max(2, int(_unit(base) * 0.4)))
    for index, (x, y) in enumerate(nodes):
        radius = _unit(base) * (1.8 if index % 2 == 0 else 1.2)
        color = colors["secondary"] if index % 2 else colors["primary"]
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    core = _unit(base) * 3.2
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=colors["primary"])


def _draw_layers(
    draw: ImageDraw.ImageDraw, colors: dict[str, str], rng: random.Random,
    width: int, height: int,
) -> None:
    """分层/架构图母题：纵向堆叠的圆角板 + 端点。"""
    base = min(width, height)
    count = rng.randint(4, 6)
    board_height = height * 0.6 / count
    board_width = width * 0.56
    left = (width - board_width) / 2
    top0 = height * 0.20
    radius = _unit(base) * 2.2
    for index in range(count):
        top = top0 + index * board_height * 1.35
        shrink = index * board_width * 0.04
        box = (left + shrink, top, left + board_width - shrink, top + board_height)
        fill = colors["dim"] if index % 2 else colors["primary"]
        outline = colors["secondary"] if index % 2 else colors["primary"]
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=max(2, int(_unit(base) * 0.5)))
        box_width = box[2] - box[0]
        for port in range(rng.randint(2, 3)):
            px = box[0] + box_width * (0.2 + 0.3 * port)
            py = (box[1] + box[3]) / 2
            pr = _unit(base) * 0.9
            draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=colors["secondary"])
    # 层间连线
    for index in range(count - 1):
        y1 = top0 + index * board_height * 1.35 + board_height
        y2 = top0 + (index + 1) * board_height * 1.35
        draw.line((width / 2, y1, width / 2, y2), fill=colors["secondary"], width=max(2, int(_unit(base) * 0.4)))


def _draw_waves(
    draw: ImageDraw.ImageDraw, colors: dict[str, str], rng: random.Random,
    width: int, height: int,
) -> None:
    """过程/信号母题：多条相位错开的波 + 波峰节点。"""
    base = min(width, height)
    center = height / 2
    amplitude = height * 0.16
    for index in range(3):
        phase = rng.uniform(0, math.tau)
        color = (colors["primary"], colors["secondary"], colors["dim"])[index]
        points = []
        for step in range(0, width + 8, 8):
            t = step / width
            y = center + math.sin(phase + t * math.pi * 2 * (1 + index)) * amplitude * (1 - index * 0.22)
            points.append((step, y))
        draw.line(points, fill=color, width=max(3, int(_unit(base) * 0.8)), joint="curve")
        px, py = points[width // 8 // 2]
        pr = _unit(base) * 1.6
        draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=colors["secondary"])
    draw.line((0, center, width, center), fill=colors["dim"], width=max(2, int(_unit(base) * 0.3)))


def _draw_blocks(
    draw: ImageDraw.ImageDraw, colors: dict[str, str], rng: random.Random,
    width: int, height: int,
) -> None:
    """结构/数据母题：块阵，部分填充强调色。"""
    base = min(width, height)
    cols = rng.randint(3, 4)
    rows = rng.randint(4, 6)
    cell = min(width * 0.7 / cols, height * 0.62 / rows)
    grid_width = cell * cols
    grid_height = cell * rows
    left = (width - grid_width) / 2
    top = (height - grid_height) / 2
    gap = cell * 0.12
    radius = cell * 0.16
    for row in range(rows):
        for col in range(cols):
            x0 = left + col * cell + gap / 2
            y0 = top + row * cell + gap / 2
            x1 = x0 + cell - gap
            y1 = y0 + cell - gap
            if rng.random() < 0.35:
                fill = colors["primary"] if rng.random() < 0.7 else colors["secondary"]
                draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill)
            else:
                draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=colors["dim"])
