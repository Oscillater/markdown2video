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
RIGHT_X = 0.2
DEFAULT_TEXT_POSITION = [0.2, 0, 0]
IMAGE_TEXT_POSITION = [0.8, -0.75, 0]
LEFT_X = -1.75
DOTS_TRANSITION_TIME = 1.0
MAX_CHARS_PER_LINE = 10
DEFAULT_DOTS_OFFSET = [RIGHT_X, 0, 0]
IMAGE_DOTS_OFFSET = [-0.5, 0, 0]

SUBTITLE_START_Y = 1.0
SCREEN_BOTTOM = -1.0
SUBTITLE_SPACING = 0.1
SUBTITLE_MAX_WIDTH = 3.0

# 默认字体
DEFAULT_FONT = "FZShuSong-Z01S"

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
    model: str = "openai:gpt-4o"  # pydantic-ai model string
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
    "stock_video": ["pexels_video", "pixabay_video", "_text_only"],
}

# These names identify render backends, not scene-level visual providers.
RENDER_BACKEND_ONLY_VISUAL_TYPES = {"manim"}


@dataclass
class ToolConfig:
    """工具注册与优先级配置。"""
    priority: dict[str, list[str]] = field(
        default_factory=lambda: dict(DEFAULT_TOOL_PRIORITY)
    )

    def get_priority(self, visual_type: str) -> list[str]:
        return self.priority.get(visual_type, ["_text_only"])

    def register(self, visual_type: str, providers: list[str]) -> None:
        self.priority[visual_type] = providers


def load_tool_config() -> ToolConfig:
    """加载工具配置（未来可从 config.yaml 读取）。"""
    return ToolConfig()


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
