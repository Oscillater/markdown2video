from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 加载 .env（如存在）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# Manim 渲染配置
MANIM_FRAME_RATE = 30
MANIM_WIDTH = 480
MANIM_HEIGHT = 854

# 默认 TTS
DEFAULT_VOICE = "zh-CN-YunxiNeural"
DEFAULT_SPEED = 1.0

# 布局常量
DEFAULT_TEXT_POSITION = [0.2, 0, 0]
IMAGE_TEXT_POSITION = [0.8, -0.75, 0]
LEFT_X = -1.75
MAX_CHARS_PER_LINE = 10

SUBTITLE_START_Y = 1.0
SCREEN_BOTTOM = -1.0
SUBTITLE_SPACING = 0.1
SUBTITLE_MAX_WIDTH = 3.0

# 风格常量已退役：字族/字号/动效/母题迁入 md2video/style 的 ink_night 设计包，
# 引擎换算只存在于 ManimRealizer（见 docs/architecture.md「Style 与 Pack」）。

# 产物目录
ARTIFACTS_DIR = Path("artifacts")
CACHE_DIR = ARTIFACTS_DIR / "cache"

# Scene 分组
MAX_SCENE_CHARS = 200  # 单 scene 内 content 累计字符上限

# LLM Planner 分块
MAX_CHUNK_SEGS = 30    # 单 chunk 最大 segment 数


# ==================== Planner 配置 ====================

@dataclass
class PlannerConfig:
    default: str = "rule"          # "rule" or "llm"
    model: str = "openai:gpt-4o"  # "openai:gpt-4o" 或裸名 "gpt-4o"（前缀在构造 LLM 请求前剥除）
    api_key: str = ""             # OpenAI-compatible API key
    base_url: str = ""            # 可选，兼容 API 地址


def load_planner_config() -> PlannerConfig:
    """从环境变量加载 planner 配置。"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return PlannerConfig(
        default=os.environ.get("MD2VIDEO_PLANNER", "rule"),
        model=os.environ.get("MD2VIDEO_LLM_MODEL", "openai:gpt-4o"),
        api_key=api_key,
        base_url=os.environ.get("MD2VIDEO_LLM_BASE_URL", ""),
    )


# ==================== Tool 配置 ====================

DEFAULT_TOOL_PRIORITY: dict[str, list[str]] = {
    "tts": ["edge-tts"],
    "stock_image": ["pexels", "local", "pixabay", "_text_only"],
    "gen_image": ["procedural"],
}

# These names identify render backends, not scene-level visual providers.
RENDER_BACKEND_ONLY_VISUAL_TYPES = {"manim"}


@dataclass
class ToolConfig:
    """工具注册与优先级配置。

    render_backend 是渲染后端（tool_type='render'）的 provider 名：
    管线按它查找渲染工具并校验返回的 provider。新后端注册进 registry
    后改这一项即可整条切换，管线代码不变。
    """
    priority: dict[str, list[str]] = field(
        default_factory=lambda: {
            kind: list(providers) for kind, providers in DEFAULT_TOOL_PRIORITY.items()
        }
    )
    render_backend: str = "manim"

    def get_priority(self, visual_type: str) -> list[str]:
        return self.priority.get(visual_type, ["_text_only"])

    def register(self, visual_type: str, providers: list[str]) -> None:
        self.priority[visual_type] = providers


def load_tool_config() -> ToolConfig:
    """加载工具配置（优先级未来可从 config.yaml 读取）。"""
    return ToolConfig(
        render_backend=os.environ.get("MD2VIDEO_RENDER_BACKEND", "manim"),
    )


# ==================== Pexels 配置 ====================

@dataclass
class PexelsConfig:
    api_key: str = ""


def load_pexels_config() -> PexelsConfig:
    """从环境变量加载 Pexels 配置。免费申请: https://www.pexels.com/api/"""
    return PexelsConfig(
        api_key=os.environ.get("PEXELS_API_KEY", ""),
    )


# ==================== Ken Burns 配置 ====================

@dataclass
class KenBurnsConfig:
    enabled: bool = True
    zoom_speed: float = 0.001     # 每帧缩放因子
    zoom_direction: str = "in"    # "in" / "out"
    fps: int = 30


def load_ken_burns_config() -> KenBurnsConfig:
    """从环境变量加载 Ken Burns 动效配置。"""
    return KenBurnsConfig(
        enabled=os.environ.get("MD2VIDEO_KEN_BURNS", "true").lower() == "true",
        zoom_speed=float(os.environ.get("MD2VIDEO_KEN_BURNS_SPEED", "0.001")),
        zoom_direction=os.environ.get("MD2VIDEO_KEN_BURNS_DIRECTION", "in"),
    )
