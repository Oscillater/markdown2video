"""Timeline invariants — 渲染后端 timeline 的纯函数时间闸门。

架构中的「时间不变量」闸门（docs/architecture.md 四道闸门）：任何渲染后端
产出的 timeline 必须先通过本模块检查，管线才允许把它当作时间事实交给
assembler 消费。检查项：

- 结构：text/markers/shots 三个列表字段存在。
- shots 覆盖 plan 的全部 shot 与 segment；start/end 数值有限且 end >= start。
- shots 按 plan 顺序排列，plan 顺序下两两不重叠（无负时长、无交叠）。
- text cue 与所属 shot 区间相交；marker 落在所属 shot 区间内。
- 朗读段时长与音频事实差值告警（只告警，不拒绝）。

纯函数：plan + execution assets + timeline dict 进，errors/warnings 出。
不做 I/O，不导入具体渲染器；渲染后端（如 manim_tool）负责接入。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from md2video.manifest.schema import ExecutionAssets, PlanManifest
from md2video.tools.render.manim_renderer_inputs import segment_uses_voiceover

REQUIRED_TIMELINE_KEYS = ("text", "markers", "shots")

# 浮点时间比较容差：manim 顺序渲染下相邻 shot 边界应精确相等，
# 容差只吸收 JSON 序列化往返的浮点噪声。
TIME_EPSILON = 1e-6

# 朗读段时长告警阈值：容忍段落内的动画开销（如字幕 Write 动画）；
# 偏差超过 max(绝对秒数, 音频时长相对比例) 才告警。
VOICEOVER_WARN_ABS_SLACK = 1.5
VOICEOVER_WARN_REL_SLACK = 0.25


@dataclass
class TimelineCheckResult:
    """check_timeline 的结果；errors 非空即拒绝该 timeline。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_timeline(
    plan: PlanManifest,
    assets: ExecutionAssets,
    timeline_data: Any,
) -> TimelineCheckResult:
    """对渲染输出的 timeline 数据执行全部时间不变量检查。"""
    check = TimelineCheckResult()

    if not isinstance(timeline_data, dict) or not set(REQUIRED_TIMELINE_KEYS).issubset(timeline_data):
        check.errors.append(
            f"Timeline missing required keys {sorted(REQUIRED_TIMELINE_KEYS)}"
        )
        return check

    for key in REQUIRED_TIMELINE_KEYS:
        if not isinstance(timeline_data[key], list):
            check.errors.append(f"Timeline field must be a list: {key}")
    if check.errors:
        return check

    shot_intervals = _collect_shot_intervals(plan, timeline_data["shots"], check)
    _check_markers(check, plan, timeline_data["markers"], shot_intervals)
    _check_shot_coverage(check, plan, timeline_data["shots"])
    _check_shot_order(check, plan, timeline_data["shots"])
    _check_shot_overlap(check, plan, shot_intervals)
    _check_text_cues(check, shot_intervals, timeline_data["text"])
    _check_voiceover_durations(check, plan, assets, timeline_data["text"])
    return check


def _coerce_time(value: Any) -> float | None:
    """把 timeline 字段值转换为有限浮点时间；不可转换时返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _plan_shot_ids(plan: PlanManifest) -> list[str]:
    return [shot.id for scene in plan.scenes for shot in scene.shots]


def _collect_shot_intervals(
    plan: PlanManifest,
    shots: list,
    check: TimelineCheckResult,
) -> dict[str, tuple[float, float]]:
    """校验 plan shot 的 start/end 并返回可用区间（无效区间已被记为 error）。"""
    required_shots = {
        shot.id: set(shot.segment_ids)
        for scene in plan.scenes
        for shot in scene.shots
    }
    if not required_shots:
        return {}

    intervals: dict[str, tuple[float, float]] = {}
    for item in shots:
        if not isinstance(item, dict):
            continue
        shot_id = item.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            continue
        if shot_id in required_shots:
            interval = _shot_interval(check, item, shot_id)
            if interval is not None:
                intervals[shot_id] = interval
    return intervals


def _shot_interval(
    check: TimelineCheckResult,
    item: dict,
    shot_id: str,
) -> tuple[float, float] | None:
    if "start" not in item or "end" not in item:
        check.errors.append(f"Timeline shot missing start/end: {shot_id}")
        return None
    try:
        start = float(item["start"])
        end = float(item["end"])
    except (TypeError, ValueError):
        check.errors.append(f"Timeline shot start/end must be numeric: {shot_id}")
        return None
    if not math.isfinite(start) or not math.isfinite(end):
        check.errors.append(f"Timeline shot start/end must be finite: {shot_id}")
        return None
    if end < start:
        check.errors.append(f"Timeline shot end before start: {shot_id}")
        return None
    return (start, end)


def _check_shot_coverage(
    check: TimelineCheckResult,
    plan: PlanManifest,
    shots: list,
) -> None:
    required_shots = {
        shot.id: set(shot.segment_ids)
        for scene in plan.scenes
        for shot in scene.shots
    }
    if not required_shots:
        return

    timeline_shots: dict[str, set[str]] = {}
    for item in shots:
        if not isinstance(item, dict):
            continue
        shot_id = item.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            continue
        segment_ids = item.get("segment_ids", [])
        if not isinstance(segment_ids, list):
            check.errors.append(
                f"Timeline shot field must be a list: segment_ids for {shot_id}"
            )
            continue
        timeline_shots.setdefault(shot_id, set()).update(
            sid for sid in segment_ids if isinstance(sid, str)
        )

    missing_shots = sorted(set(required_shots) - set(timeline_shots))
    if missing_shots:
        check.errors.append(f"Timeline missing plan shots: {missing_shots}")

    missing_segments = {
        shot_id: sorted(required_segments - timeline_shots.get(shot_id, set()))
        for shot_id, required_segments in required_shots.items()
        if required_segments - timeline_shots.get(shot_id, set())
    }
    if missing_segments:
        details = "; ".join(
            f"{shot_id}: {segment_ids}"
            for shot_id, segment_ids in sorted(missing_segments.items())
        )
        check.errors.append(f"Timeline missing plan segments: {details}")


def _check_shot_order(
    check: TimelineCheckResult,
    plan: PlanManifest,
    shots: list,
) -> None:
    """timeline 中匹配 plan 的 shot 条目必须按 plan 的 scene/shot 顺序出现。"""
    plan_order = _plan_shot_ids(plan)
    plan_index = {shot_id: index for index, shot_id in enumerate(plan_order)}
    timeline_ids = [
        item.get("shot_id")
        for item in shots
        if isinstance(item, dict)
        and isinstance(item.get("shot_id"), str)
        and item.get("shot_id") in plan_index
    ]
    positions = [plan_index[shot_id] for shot_id in timeline_ids]
    if positions != sorted(positions):
        check.errors.append(
            f"Timeline shots out of plan order: {timeline_ids} "
            f"(plan order: {plan_order})"
        )


def _check_shot_overlap(
    check: TimelineCheckResult,
    plan: PlanManifest,
    intervals: dict[str, tuple[float, float]],
) -> None:
    """plan 顺序下相邻 shot 区间不允许交叠（允许空隙）。"""
    for prev_id, next_id in zip(_plan_shot_ids(plan), _plan_shot_ids(plan)[1:]):
        if prev_id not in intervals or next_id not in intervals:
            continue
        prev_end = intervals[prev_id][1]
        next_start = intervals[next_id][0]
        if next_start < prev_end - TIME_EPSILON:
            check.errors.append(
                f"Timeline shots overlap: shot {next_id} starts at {next_start:.3f} "
                f"before shot {prev_id} ends at {prev_end:.3f}"
            )


def _required_marker_shot_by_id(plan: PlanManifest) -> dict[str, str]:
    """plan 中全部 marker cue：cue id -> 所属 shot id。"""
    required: dict[str, str] = {}
    for scene in plan.scenes:
        for shot in scene.shots:
            for cue in shot.cues:
                if (
                    cue.get("cue_type") in ("marker_music", "marker_image")
                    and cue.get("id")
                ):
                    required[str(cue["id"])] = shot.id
    return required


def _check_markers(
    check: TimelineCheckResult,
    plan: PlanManifest,
    markers: list,
    shot_intervals: dict[str, tuple[float, float]],
) -> None:
    required_markers = _required_marker_shot_by_id(plan)
    if not required_markers:
        return

    markers_by_id: dict[str, dict] = {}
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        for marker_id in (marker.get("id"), marker.get("segment_id")):
            if isinstance(marker_id, str) and marker_id in required_markers:
                markers_by_id[marker_id] = marker

    missing_markers = [
        marker_id for marker_id in required_markers if marker_id not in markers_by_id
    ]
    if missing_markers:
        check.errors.append(f"Timeline missing marker entries: {missing_markers}")

    invalid_times = []
    outside_shots = []
    for marker_id in required_markers:
        marker = markers_by_id.get(marker_id)
        if marker is None:
            continue
        marker_time = _coerce_time(marker.get("time"))
        if marker_time is None:
            invalid_times.append(marker_id)
            continue
        shot_id = required_markers[marker_id]
        interval = shot_intervals.get(shot_id)
        if interval is None:
            continue
        shot_start, shot_end = interval
        if marker_time < shot_start - TIME_EPSILON or marker_time > shot_end + TIME_EPSILON:
            outside_shots.append(
                f"{marker_id} (t={marker_time:.3f} outside shot {shot_id} "
                f"[{shot_start:.3f}, {shot_end:.3f}])"
            )

    if invalid_times:
        check.errors.append(
            f"Timeline marker time must be numeric and finite: {invalid_times}"
        )
    if outside_shots:
        check.errors.append(
            "Timeline marker outside its shot interval: " + ", ".join(outside_shots)
        )


def _check_text_cues(
    check: TimelineCheckResult,
    shot_intervals: dict[str, tuple[float, float]],
    text_entries: list,
) -> None:
    """每个可归属到 plan shot 的 text cue 必须与该 shot 区间相交。

    堆叠字幕等跨 shot 持续显示的文本会在起点 shot 之后才关闭，
    所以这里检查相交而不是严格包含。
    """
    if not shot_intervals:
        return
    for entry in text_entries:
        if not isinstance(entry, dict):
            continue
        shot_id = entry.get("shot_id")
        if not isinstance(shot_id, str) or shot_id not in shot_intervals:
            continue
        segment_id = entry.get("segment_id", "<unknown>")
        start = _coerce_time(entry.get("start"))
        end = _coerce_time(entry.get("end"))
        if start is None or end is None:
            check.warnings.append(
                f"Timeline text cue has missing or non-finite timing: "
                f"segment {segment_id} in shot {shot_id}"
            )
            continue
        shot_start, shot_end = shot_intervals[shot_id]
        if start > shot_end + TIME_EPSILON or end < shot_start - TIME_EPSILON:
            check.errors.append(
                f"Timeline text cue outside its shot interval: segment {segment_id} "
                f"[{start:.3f}, {end:.3f}] vs shot {shot_id} "
                f"[{shot_start:.3f}, {shot_end:.3f}]"
            )


def _check_voiceover_durations(
    check: TimelineCheckResult,
    plan: PlanManifest,
    assets: ExecutionAssets,
    text_entries: list,
) -> None:
    """朗读段 text cue 时长与音频事实差值超过容忍度时告警（不拒绝）。

    text cue 度量的是可见时长而非朗读时长：section header 的堆叠字幕
    有意持续显示到被顶掉或收尾，超长是设计行为，只对 visibility 应跟随
    语音的段落类型（content/appendix）告警；朗读被截短则任何类型都告警。
    """
    audio_duration_by_segment = {
        asset.segment_id: float(asset.duration)
        for asset in assets.audio_assets
        if asset.duration > 0
    }
    cue_spans_by_segment: dict[str, list[tuple[float, float]]] = {}
    for entry in text_entries:
        if not isinstance(entry, dict):
            continue
        segment_id = entry.get("segment_id")
        start = _coerce_time(entry.get("start"))
        end = _coerce_time(entry.get("end"))
        if isinstance(segment_id, str) and start is not None and end is not None:
            cue_spans_by_segment.setdefault(segment_id, []).append((start, end))

    for segment in plan.segments:
        if not segment_uses_voiceover(segment):
            continue
        audio_duration = audio_duration_by_segment.get(segment.id)
        if audio_duration is None:
            continue
        spans = cue_spans_by_segment.get(segment.id)
        if not spans:
            check.warnings.append(
                f"Timeline has no text cue for voiced segment: {segment.id}"
            )
            continue
        slack = max(
            VOICEOVER_WARN_ABS_SLACK,
            VOICEOVER_WARN_REL_SLACK * audio_duration,
        )
        persistent_subtitle = segment.segment_type == "section_header"
        for start, end in spans:
            cue_duration = end - start
            if cue_duration <= 0:
                continue
            deviation = cue_duration - audio_duration
            truncated = deviation < -slack
            overlong = deviation > slack and not persistent_subtitle
            if truncated or overlong:
                check.warnings.append(
                    f"Voiceover duration mismatch for segment {segment.id}: "
                    f"text cue {cue_duration:.2f}s vs audio {audio_duration:.2f}s"
                )
