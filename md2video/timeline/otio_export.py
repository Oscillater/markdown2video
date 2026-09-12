"""timeline.json → OpenTimelineIO 导出（A9，交付形态）。

timeline 是 renderer 产出的时间事实；OTIO 是同一事实面向剪辑生态
（EDL / FCPXML / AAF / Resolve）的交换序列化。归 infra：它是 result 的
另一种 serialization，不是 harness 功能。映射规则：

- `shots` 主时间轴 → Video track 上的 Clip 序列：clip 名 = shot_id，
  source_range = shot 的 [start, end)（底片与时间轴同刻度）；scene_id /
  layout_type / segment_ids 进 clip metadata["md2video"]。
- `markers`（时间点事件 cue）→ 挂到所属 shot 的 Clip 上成为 OTIO
  Marker：marked_range 起点 = marker 绝对时间 - shot 起点；事件字段
  （cue_type/kind/name）进 marker metadata["md2video"]。
- `text`（可见文本 cue）→ OTIO 没有文本原语，作为事实挂到起点落进的
  shot Clip metadata["md2video"]["text"]；text 允许跨 shot 持续显示
  （invariants 只查相交），所以按起点归属。无可归属 shot 的 text 进
  Timeline metadata["md2video"]["orphan_text"]。
- fps 优先取 timeline 携带的 `fps` 字段（渲染契约未来可能多帧率），否则
  用渲染契约默认（manim.cfg 声明的 30）。

纯函数：timeline dict 进，otio Timeline / .otio 文件出。不做时间校验——
那是闸门（invariants）的事，这里只翻译已被闸门放行的事实；坏条目跳过
不抛错，保证导出永不比闸门更严格。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# 渲染契约默认帧率（manim.cfg frame_rate；A2.5 之后所有后端同契约）。
DEFAULT_TIMELINE_FPS = 30.0

OTIO_FILENAME = "timeline.otio"


def _resolve_fps(timeline_data: dict) -> float:
    raw = timeline_data.get("fps")
    try:
        fps = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMELINE_FPS
    return fps if fps > 0 else DEFAULT_TIMELINE_FPS


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _shot_intervals(shots: list) -> list[tuple[float, float, dict]]:
    """按 start 排序的 (start, end, entry) 列表；坏条目跳过。"""
    intervals = []
    for entry in shots:
        if not isinstance(entry, dict):
            continue
        start = _finite(entry.get("start"))
        end = _finite(entry.get("end"))
        if start is None or end is None or end < start:
            continue
        intervals.append((start, end, entry))
    intervals.sort(key=lambda item: (item[0], item[1]))
    return intervals


def _shot_id_of(entry: dict) -> str:
    shot_id = entry.get("shot_id")
    return shot_id if isinstance(shot_id, str) else ""


def _md_metadata(entry: dict) -> dict:
    metadata: dict = {}
    if entry.get("scene_id"):
        metadata["scene_id"] = entry["scene_id"]
    if entry.get("layout_type"):
        metadata["layout_type"] = entry["layout_type"]
    if isinstance(entry.get("segment_ids"), list):
        metadata["segment_ids"] = list(entry["segment_ids"])
    return metadata


def _containing_shot(
    time_value: float,
    intervals: list[tuple[float, float, dict]],
) -> dict | None:
    """起点落进的 shot（start <= t < end，末尾闭区间）；找不到返回 None。"""
    for start, end, entry in intervals:
        if start <= time_value < end:
            return entry
    if intervals and time_value >= intervals[-1][1]:
        return intervals[-1][2]
    return None


def timeline_to_otio(timeline_data: dict, *, name: str = ""):
    """把 timeline dict 翻译成 OTIO Timeline 对象（需要 opentimelineio）。"""
    import opentimelineio as otio

    fps = _resolve_fps(timeline_data)

    def seconds(value: float):
        return otio.opentime.from_seconds(max(0.0, value), rate=fps)

    otio_timeline = otio.schema.Timeline(
        name=name,
        # 外部读入方（NLE 导入器等）习惯从 global_start_time.rate 取时间线帧率
        global_start_time=otio.opentime.RationalTime(0, fps),
        metadata={"md2video": {"fps": fps, "generator": "markdown2video"}},
    )
    track = otio.schema.Track(name="shots", kind=otio.schema.TrackKind.Video)
    otio_timeline.tracks.append(track)

    intervals = _shot_intervals(timeline_data.get("shots") or [])
    clips_by_shot_id: dict[str, Any] = {}
    orphan_text: list[dict] = []
    orphan_markers: list[dict] = []

    for start, end, entry in intervals:
        shot_id = _shot_id_of(entry) or f"shot@{start:.3f}"
        duration = max(0.0, end - start)
        clip = otio.schema.Clip(
            name=shot_id,
            source_range=otio.opentime.TimeRange(
                start_time=seconds(start),
                duration=seconds(duration),
            ),
            metadata={"md2video": _md_metadata(entry)},
        )
        track.append(clip)
        if _shot_id_of(entry):
            clips_by_shot_id[shot_id] = clip

    def clip_for_attachment(entry: dict, time_value: float | None):
        """归属优先级：显式 shot_id > 时间落入的 shot > None。"""
        shot_id = _shot_id_of(entry)
        if not shot_id and time_value is not None:
            container = _containing_shot(time_value, intervals)
            shot_id = _shot_id_of(container) if container is not None else ""
        return clips_by_shot_id.get(shot_id) if shot_id else None

    for entry in timeline_data.get("text") or []:
        if not isinstance(entry, dict):
            continue
        start = _finite(entry.get("start"))
        end = _finite(entry.get("end"))
        if start is None or end is None:
            continue
        clip = clip_for_attachment(entry, start)
        fact = {
            "segment_id": entry.get("segment_id", ""),
            "segment_type": entry.get("segment_type", ""),
            "text": entry.get("text", ""),
            "start": start,
            "end": end,
        }
        if clip is None:
            orphan_text.append(fact)
        else:
            clip.metadata["md2video"].setdefault("text", []).append(fact)

    for entry in timeline_data.get("markers") or []:
        if not isinstance(entry, dict):
            continue
        time_value = _finite(entry.get("time"))
        if time_value is None:
            continue
        clip = clip_for_attachment(entry, time_value)
        marker = otio.schema.Marker(
            name=str(entry.get("id") or entry.get("name") or f"marker@{time_value:.3f}"),
            marked_range=otio.opentime.TimeRange(
                start_time=seconds(time_value),
                duration=seconds(0.0),
            ),
            metadata={"md2video": {
                "cue_type": entry.get("cue_type", ""),
                "kind": entry.get("kind", ""),
                "time": time_value,
            }},
        )
        if clip is None:
            orphan_markers.append(entry)
        else:
            clip.markers.append(marker)

    if orphan_text:
        otio_timeline.metadata["md2video"]["orphan_text"] = orphan_text
    if orphan_markers:
        otio_timeline.metadata["md2video"]["orphan_markers"] = orphan_markers
    return otio_timeline


def export_timeline_otio(
    timeline_data: dict,
    out_path: Path,
    *,
    name: str = "",
) -> Path:
    """把 timeline dict 导出为 .otio 文件（需要 opentimelineio）。"""
    import opentimelineio as otio

    otio.adapters.write_to_file(
        timeline_to_otio(timeline_data, name=name),
        str(out_path),
    )
    return out_path


def write_otio_artifact(
    timeline_data: dict,
    out_path: Path,
    *,
    name: str = "",
) -> tuple[Path | None, str]:
    """尽力导出：库缺失/翻译失败返回 (None, warning)，不阻断交付（降级链）。"""
    try:
        export_timeline_otio(timeline_data, out_path, name=name)
        return out_path, ""
    except ImportError:
        return None, "opentimelineio not installed; OTIO export skipped"
    except Exception as exc:
        return None, f"OTIO export failed: {exc}"
