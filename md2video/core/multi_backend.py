"""按 scene 多后端分发与合成基础设施（A6 前半）。

相邻同后端的 scene 组成极大组：plan 切片 → 各后端从 t=0 渲自己的切片
（局部视频 + 局部 timeline）→ timeline 前缀偏移合并 → 视频拼接。引擎切
换即场景切换：每组一次独立渲染调用，渲染器内部跨 shot 状态（字幕堆叠/
母题）在组边界天然清零。合并后的 timeline 对完整 plan 重过全局时间不变
量闸门，拼接出的底片交给 assembler 走既有合成路径（成片规格一致）。
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from md2video.assembler.ffmpeg_assembler import has_audio_stream
from md2video.manifest.schema import ExecutionAssets, PlanManifest, ScenePlan
from md2video.timeline.invariants import check_timeline


@dataclass
class RenderGroup:
    """一个极大同后端 scene 组（按 plan 顺序相邻）。"""

    backend: str
    scenes: list[ScenePlan] = field(default_factory=list)


def effective_backend(scene: ScenePlan, default_backend: str) -> str:
    """scene 级 render_backend 优先；空值回退到配置的默认后端。"""
    return scene.render_backend or default_backend


def plan_render_groups(plan: PlanManifest, default_backend: str) -> list[RenderGroup]:
    """把 plan 的 scene 序列切成极大同后端组。"""
    groups: list[RenderGroup] = []
    for scene in plan.scenes:
        backend = effective_backend(scene, default_backend)
        if groups and groups[-1].backend == backend:
            groups[-1].scenes.append(scene)
        else:
            groups.append(RenderGroup(backend=backend, scenes=[scene]))
    return groups


def slice_plan(plan: PlanManifest, scenes: list[ScenePlan]) -> PlanManifest:
    """切出只含给定 scene 的 plan 切片（渲染后端的完整合法输入）。

    segments 只保留切片 shot 引用的内容字典条目：渲染器要求全部可渲染
    segment 都被 shot 覆盖，带上未引用段会触发 orphan fail fast。
    """
    referenced: set[str] = {
        sid for scene in scenes for shot in scene.shots for sid in shot.segment_ids
    }
    return PlanManifest(
        version=plan.version,
        segments=[seg for seg in plan.segments if seg.id in referenced],
        scenes=list(scenes),
        media_declarations=dict(plan.media_declarations),
    )


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _group_duration(local: dict) -> float:
    """局部组的时长 = 局部主时间轴的末 shot end（shot 是主时间轴）。"""
    ends = [
        end
        for shot in local.get("shots", [])
        if isinstance(shot, dict)
        for end in [_finite(shot.get("end"))]
        if end is not None
    ]
    return max(ends, default=0.0)


def _shift_shot(shot: dict, offset: float) -> dict:
    shifted = dict(shot)
    start = _finite(shot.get("start"))
    end = _finite(shot.get("end"))
    if start is not None:
        shifted["start"] = start + offset
    if end is not None:
        shifted["end"] = end + offset
    return shifted


def _shift_text(entry: dict, offset: float) -> dict:
    shifted = dict(entry)
    start = _finite(entry.get("start"))
    end = _finite(entry.get("end"))
    if start is not None:
        shifted["start"] = start + offset
    if end is not None:
        shifted["end"] = end + offset
    return shifted


def _shift_marker(entry: dict, offset: float) -> dict:
    shifted = dict(entry)
    time = _finite(entry.get("time"))
    if time is not None:
        shifted["time"] = time + offset
    return shifted


def merge_group_timelines(local_timelines: list[dict]) -> dict:
    """把各组的局部 timeline（各自从 t=0）按组顺序做前缀偏移合并。"""
    merged: dict[str, list] = {"text": [], "markers": [], "shots": []}
    offset = 0.0
    for local in local_timelines:
        merged["shots"].extend(
            _shift_shot(shot, offset)
            for shot in local.get("shots", [])
            if isinstance(shot, dict)
        )
        merged["text"].extend(
            _shift_text(entry, offset)
            for entry in local.get("text", [])
            if isinstance(entry, dict)
        )
        merged["markers"].extend(
            _shift_marker(entry, offset)
            for entry in local.get("markers", [])
            if isinstance(entry, dict)
        )
        offset += _group_duration(local)
    return merged


def check_merged_timeline(
    plan: PlanManifest,
    assets: ExecutionAssets,
    merged_timeline: dict,
) -> None:
    """全局闸门：合并后的 timeline 必须对完整 plan 通过全部时间不变量。"""
    check = check_timeline(plan, assets, merged_timeline)
    if not check.ok:
        raise RuntimeError(
            "Merged timeline failed global invariants: "
            + " | ".join(check.errors)
        )
    for warning in check.warnings:
        print(f"  Timeline warning: {warning}")


def concat_group_videos(videos: list[Path], out_path: Path) -> Path:
    """按组顺序拼接局部底片，输出仍是 assembler 可消费的标准底片。

    音轨策略：任一组有音轨时，无音轨的组补静音轨保证 concat 输入一致；
    全部组都静音时拼出无音轨底片，让 assembler 走它已验证的 anullsrc
    静音路径（纯数字静音直接过 loudnorm 会产生 NaN，见 assembler）。
    拼接是编码级 concat filter；单后端 run 不经过这里，行为保持与现状
    逐帧一致。
    """
    if not videos:
        raise ValueError("No group videos to concat")
    if len(videos) == 1:
        raise ValueError("Single group does not need concat")

    cmd: list[str] = ["ffmpeg", "-y", "-v", "error"]
    stream_labels: list[str] = []
    next_index = 0
    if any(has_audio_stream(video) for video in videos):
        for video in videos:
            cmd += ["-i", str(video)]
            video_label = f"[{next_index}:v]"
            audio_label = f"[{next_index}:a]"
            if not has_audio_stream(video):
                duration = _probe_duration(video)
                cmd += [
                    "-f", "lavfi", "-t", f"{duration:.6f}",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                ]
                audio_label = f"[{next_index + 1}:a]"
                next_index += 1
            stream_labels.append(f"{video_label}{audio_label}")
            next_index += 1
        audio_spec = "a=1[v][a]"
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    else:
        with_audio = False
        for video in videos:
            cmd += ["-i", str(video)]
            stream_labels.append(f"[{next_index}:v]")
            next_index += 1
        audio_spec = "a=0[v]"
        maps = ["-map", "[v]"]

    filter_complex = (
        f"{''.join(stream_labels)}concat=n={len(videos)}:v=1:{audio_spec}"
    )
    cmd += [
        "-filter_complex", filter_complex,
        *maps,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Group video concat failed: {proc.stderr[-500:]}")
    return out_path


def _probe_duration(video: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Cannot probe duration of {video}") from exc
