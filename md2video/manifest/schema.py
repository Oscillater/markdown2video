from __future__ import annotations

from typing import Optional, Dict, List
from pydantic import BaseModel, Field, model_validator


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


class ShotPlan(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)
    target_duration: float = 0.0  # TTS 时长，视觉工具必须适配此时长


class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = Field(default_factory=dict)
    shots: List[ShotPlan] = Field(default_factory=list)
    section_context: str = ""
    # 向后兼容: 旧 JSON 含 segment_ids 时自动迁移为单 Shot
    segment_ids: Optional[List[str]] = Field(default=None, exclude=True)

    @property
    def all_segment_ids(self) -> List[str]:
        return [sid for shot in self.shots for sid in shot.segment_ids]

    @model_validator(mode="after")
    def _migrate_segment_ids(self):
        if self.segment_ids is not None and not self.shots:
            self.shots = [ShotPlan(
                id=f"{self.id}_shot_001",
                segment_ids=self.segment_ids,
            )]
        return self


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


class ShotResult(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    visual: VisualResult = Field(default_factory=VisualResult)


class SceneResult(BaseModel):
    id: str
    shots: List[ShotResult] = Field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    # 向后兼容: 旧 JSON 含 segment_ids/visual 时自动迁移为单 Shot
    segment_ids: Optional[List[str]] = Field(default=None, exclude=True)
    visual: Optional[VisualResult] = Field(default=None, exclude=True)

    @property
    def all_segment_ids(self) -> List[str]:
        return [sid for shot in self.shots for sid in shot.segment_ids]

    @model_validator(mode="after")
    def _migrate_and_sync(self):
        if self.segment_ids is not None and not self.shots:
            self.shots = [ShotResult(
                id=f"{self.id}_shot_001",
                segment_ids=self.segment_ids,
                start=self.start,
                end=self.end,
                visual=self.visual or VisualResult(),
            )]
        # 从 shots 聚合 start/end
        if self.shots:
            self.start = min(s.start for s in self.shots)
            self.end = max(s.end for s in self.shots)
        return self


class ResultManifest(BaseModel):
    segments: List[SegmentResult] = Field(default_factory=list)
    scenes: List[SceneResult] = Field(default_factory=list)
