"""时长估算器 — 只服务容错决策与展示，永不用于组合。

裁决唯一：段时长 = 音频事实 > hold cue > pack 节奏（裁决函数住在渲染
执行里）。本模块是估算视图：用音频事实 + pack 节奏 + 转场开销常数给出
预计总时长，供配乐选择、总长告警与检查页展示；它的输出不许回流到
plan、渲染或合成的任何组合路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from md2video.manifest.schema import ExecutionAssets, PlanManifest
from md2video.style.schema import ThemeTokens
from md2video.tools.render.manim_renderer_inputs import (
    TITLE_SEGMENT_TYPES,
    segment_uses_voiceover,
)

# 转场开销常数：意图级动效不规定精确时长，估算用单一常数近似
# "这一段出现动画占掉的时间"。静默 body 段是直接 add（无动画），不计入。
TRANSITION_OVERHEAD_SECONDS = 1.0

_MARKER_SEGMENT_TYPES = {"marker_music", "marker_image"}


@dataclass
class DurationEstimate:
    """预计时长分解（估算值，不是时间事实）。"""

    total_seconds: float
    voiced_seconds: float
    silent_seconds: float
    overhead_seconds: float
    per_segment: dict[str, float] = field(default_factory=dict)


def estimate_plan_duration(
    plan: PlanManifest,
    assets: ExecutionAssets,
    tokens: ThemeTokens,
    *,
    transition_overhead: float = TRANSITION_OVERHEAD_SECONDS,
) -> DurationEstimate:
    """按渲染顺序估算 plan 的预计时长。

    模型（近似）：

    - 有声段：音频事实时长；section header 另加一次转场开销
      （Write 动画在语音之前播放）。
    - 静默段：pack 节奏（silent.body / silent.section_header）；
      section header 另加转场开销，静默 body 直接出现不加。
    - 标题卡片只计一次：title_hold + 一次转场开销。
    - marker 是 0 时长时间点事件。
    """
    audio_duration_by_segment = {
        asset.segment_id: float(asset.duration)
        for asset in assets.audio_assets
        if asset.duration > 0
    }
    segment_by_id = {segment.id: segment for segment in plan.segments}

    voiced = 0.0
    silent = 0.0
    overhead = 0.0
    per_segment: dict[str, float] = {}
    title_counted = False

    def account(segment_id: str, seconds: float, kind: str) -> None:
        nonlocal voiced, silent, overhead
        per_segment[segment_id] = seconds
        if kind == "voiced":
            voiced += seconds
        else:
            silent += seconds

    # 标题卡片：title segment 不进 body 遍历，按一次卡片开销估算
    for segment in plan.segments:
        if segment.segment_type in TITLE_SEGMENT_TYPES and segment.id not in per_segment:
            if title_counted:
                per_segment[segment.id] = 0.0
                continue
            title_counted = True
            seconds = tokens.motion.silent.title_hold + transition_overhead
            overhead += transition_overhead
            account(segment.id, seconds, "silent")

    for scene in plan.scenes:
        for shot in scene.shots:
            for segment_id in shot.segment_ids:
                segment = segment_by_id.get(segment_id)
                if segment is None or segment.segment_type in _MARKER_SEGMENT_TYPES:
                    continue
                if segment.segment_type in TITLE_SEGMENT_TYPES:
                    continue
                audio_duration = audio_duration_by_segment.get(segment.id)
                if segment_uses_voiceover(segment) and audio_duration is not None:
                    seconds = audio_duration
                    if segment.segment_type == "section_header":
                        seconds += transition_overhead
                        overhead += transition_overhead
                    account(segment.id, seconds, "voiced")
                else:
                    if segment.segment_type == "section_header":
                        seconds = (
                            tokens.motion.silent.section_header + transition_overhead
                        )
                        overhead += transition_overhead
                    else:
                        seconds = tokens.motion.silent.body
                    account(segment.id, seconds, "silent")

    return DurationEstimate(
        total_seconds=voiced + silent,
        voiced_seconds=voiced,
        silent_seconds=silent,
        overhead_seconds=overhead,
        per_segment=per_segment,
    )
