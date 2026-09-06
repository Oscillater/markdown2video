from __future__ import annotations

from typing import Any, Optional, Dict, List
from pydantic import BaseModel, ConfigDict, Field, model_validator

from md2video.layout.schema import DEFAULT_LAYOUT_TYPE


# ==================== Plan Manifest ====================

class AudioRequest(BaseModel):
    voice: str = "zh-CN-YunxiNeural"
    speed: float = 1.0
    format: str = "wav"


class SegmentPlan(BaseModel):
    """内容原子：只描述内容与朗读意图。

    plan 不含时间（时长是事实，谁产出谁发现），也不含 visual/layout
    取值——那些决策在 scene 级。v1 的 target_duration 与 visual/layout
    副本字段已在 v2 迁移中移除（见 md2video/manifest/migration.py）。
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    segment_type: str  # title_main, title_sub, section_header, content, appendix, marker_music, marker_image
    audio_request: Optional[AudioRequest] = None
    explicit: bool = False
    # 上下文信息
    section_context: str = ""  # 所属的 h3 标题
    marker_data: Optional[Dict] = None  # marker 类型: {"kind": "start/end", "name": "xxx"}


class ShotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    segment_ids: List[str] = Field(default_factory=list)
    cues: List[Dict[str, Any]] = Field(default_factory=list)


class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = Field(default_factory=dict)
    layout_type: str = DEFAULT_LAYOUT_TYPE
    layout_params: Dict = Field(default_factory=dict)
    # A5 直接提案入口：归一化 region 集合（name -> {x,y,width,height}）。
    # 与模板产出走同一套 ComputedLayout 属性校验；设置时优先于 layout_type。
    layout_regions: Optional[Dict[str, Dict[str, float]]] = None
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
    version: str = "2"
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


# ==================== Runtime Artifacts ====================

class AudioAsset(BaseModel):
    segment_id: str
    path: str
    duration: float
    provider: str = "edge-tts"
    cache_key: str = ""


class VisualAsset(BaseModel):
    shot_id: str
    path: str
    width: int = 0
    height: int = 0
    provider: str = "none"
    cache_key: str = ""
    source_url: str = ""
    # duration 合同：会占用时间轴的素材由素材工具 probe 上报（静态图片为 0）
    duration: float = 0.0


class ExecutionAssets(BaseModel):
    """Material facts produced during one runtime execution."""

    version: str = "1"
    audio_assets: List[AudioAsset] = Field(default_factory=list)
    visual_assets: List[VisualAsset] = Field(default_factory=list)


class FinalResultManifest(BaseModel):
    """Final delivery summary written after assemble completes.

    run_id 把这份 result 绑定到 artifacts/runs/<run_id>/ 目录；status 取值
    "completed" / "failed"（失败 run 在自己的 run 目录写 failed result，
    旧 run 的 result 永不被触碰——区分只靠 run_id 与命名）。
    """

    version: str = "1"
    run_id: str = ""
    status: str = "completed"
    output_mp4: str
    used_assets: Dict[str, List[Dict]] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    artifact_index: Dict[str, str] = Field(default_factory=dict)


def result_manifest_from_execution_assets(
    plan: PlanManifest,
    assets: ExecutionAssets,
) -> ResultManifest:
    """Build the legacy in-memory result view from runtime execution assets."""

    audio_by_segment = {asset.segment_id: asset for asset in assets.audio_assets}
    visual_by_shot = {asset.shot_id: asset for asset in assets.visual_assets}
    segment_by_id = {seg.id: seg for seg in plan.segments}
    segment_result_by_id: Dict[str, SegmentResult] = {}

    def _audio_result(segment_id: str) -> Optional[AudioResult]:
        audio_asset = audio_by_segment.get(segment_id)
        if not audio_asset:
            return None
        return AudioResult(
            path=audio_asset.path,
            duration=audio_asset.duration,
            provider=audio_asset.provider,
            cache_key=audio_asset.cache_key,
        )

    def _assign_segment(segment_id: str, start: float, end: float) -> SegmentResult:
        existing = segment_result_by_id.get(segment_id)
        if existing:
            return existing
        result = SegmentResult(
            id=segment_id,
            audio=_audio_result(segment_id),
            start=start,
            end=end,
        )
        segment_result_by_id[segment_id] = result
        return result

    current_time = 0.0
    scene_results: List[SceneResult] = []
    for scene in plan.scenes:
        shot_results: List[ShotResult] = []
        for shot in scene.shots:
            shot_segment_ids = [
                sid for sid in shot.segment_ids
                if sid in segment_by_id
            ]
            if not shot_segment_ids:
                continue

            shot_start = current_time
            segment_results_for_shot: List[SegmentResult] = []

            segment_time = current_time
            for sid in shot_segment_ids:
                if sid in audio_by_segment:
                    duration = audio_by_segment[sid].duration
                else:
                    # plan 不含时间：无音频事实的段在 result 里 0 时长，
                    # 实际静默时长由渲染器按 pack 节奏发现并写进 timeline。
                    duration = 0.0
                segment_results_for_shot.append(
                    _assign_segment(sid, segment_time, segment_time + duration)
                )
                segment_time += duration
            current_time = segment_time

            if not shot_segment_ids and not shot.cues:
                continue

            visual_asset = visual_by_shot.get(shot.id)
            visual = VisualResult()
            if visual_asset:
                visual = VisualResult(
                    path=visual_asset.path,
                    width=visual_asset.width,
                    height=visual_asset.height,
                    source=visual_asset.provider,
                )
            shot_results.append(ShotResult(
                id=shot.id,
                segment_ids=shot.segment_ids,
                start=shot_start,
                end=current_time,
                visual=visual,
            ))

        if shot_results:
            scene_results.append(SceneResult(
                id=scene.id,
                shots=shot_results,
                start=min(sr.start for sr in shot_results),
                end=max(sr.end for sr in shot_results),
            ))

    for seg in plan.segments:
        if seg.id in segment_result_by_id:
            continue
        audio_asset = audio_by_segment.get(seg.id)
        duration = audio_asset.duration if audio_asset else 0.0
        _assign_segment(seg.id, current_time, current_time + duration)
        current_time += duration

    segment_results = [
        segment_result_by_id[seg.id]
        for seg in plan.segments
        if seg.id in segment_result_by_id
    ]

    return ResultManifest(segments=segment_results, scenes=scene_results)
