from __future__ import annotations

from typing import Optional, Dict, List
from pydantic import BaseModel, Field


# ==================== Plan Manifest ====================

class AudioRequest(BaseModel):
    voice: str = "zh-CN-YunxiNeural"
    speed: float = 1.0
    format: str = "wav"


class SegmentPlan(BaseModel):
    id: str
    text: str
    segment_type: str  # title_main, title_sub, section_header, content, appendix, marker_music, marker_image
    visual_type: str = "text_only"
    visual_params: Dict = Field(default_factory=dict)
    audio_request: Optional[AudioRequest] = None
    explicit: bool = False
    # 上下文信息
    section_context: str = ""  # 所属的 h3 标题
    marker_data: Optional[Dict] = None  # marker 类型: {"kind": "start/end", "name": "xxx"}


class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = Field(default_factory=dict)
    segment_ids: List[str] = Field(default_factory=list)
    section_context: str = ""


class PlanManifest(BaseModel):
    version: str = "1"
    segments: List[SegmentPlan] = Field(default_factory=list)
    scenes: List[ScenePlan] = Field(default_factory=list)
    media_declarations: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    # {"music": {"bgm": "./music.mp3"}, "images": {"logo": "./assets/logo.png"}}


# ==================== Result Manifest ====================

class AudioResult(BaseModel):
    path: str
    duration: float
    provider: str = "edge-tts"
    cache_key: str = ""


class VisualResult(BaseModel):
    path: str = ""
    width: int = 0
    height: int = 0
    source: str = "none"


class SegmentResult(BaseModel):
    id: str
    audio: Optional[AudioResult] = None
    visual: VisualResult = Field(default_factory=VisualResult)
    start: float = 0.0
    end: float = 0.0


class SceneResult(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    visual: VisualResult = Field(default_factory=VisualResult)


class ResultManifest(BaseModel):
    segments: List[SegmentResult] = Field(default_factory=list)
    scenes: List[SceneResult] = Field(default_factory=list)
