"""ManimRenderTool — standard render Tool backend for Manim."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from md2video.manifest.schema import ExecutionAssets, PlanManifest
from md2video.tools.render.manim_renderer_inputs import validate_renderer_inputs


class ManimRenderTool:
    """Render the base video by running the ManifestDrivenScene through Manim."""

    def __init__(self, project_root: str | Path | None = None):
        self.project_root = Path(project_root) if project_root else Path(__file__).parents[3]
        self.renderer_src = Path(__file__).with_name("manim_renderer.py")
        self.manim_cfg_src = Path(__file__).with_name("manim.cfg")

    @property
    def tool_type(self) -> str:
        return "render"

    @property
    def provider_name(self) -> str:
        return "manim"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run Manim with explicit manifest inputs and return rendered artifacts."""
        plan_path = self._required_path(input_data, "plan_path")
        assets_path = self._required_path(input_data, "execution_assets_path")
        timeline_path = Path(self._required_value(input_data, "timeline_path"))
        output_dir = Path(input_data.get("output_dir", timeline_path.parent))
        quality = str(input_data.get("quality", "ql"))
        timeout = int(input_data.get("timeout", 300))

        if not plan_path.exists():
            raise FileNotFoundError(f"Plan manifest not found: {plan_path}")
        if not assets_path.exists():
            raise FileNotFoundError(f"Execution assets not found: {assets_path}")

        plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
        assets = ExecutionAssets.model_validate_json(assets_path.read_text(encoding="utf-8"))
        validate_renderer_inputs(plan, assets)

        output_dir.mkdir(parents=True, exist_ok=True)
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        if timeline_path.exists():
            timeline_path.unlink()

        anim_dir = Path(tempfile.mkdtemp(prefix="manim_render_", dir=output_dir))
        anim_renderer = anim_dir / "manifest_scene.py"
        anim_cfg = anim_dir / "manim.cfg"

        shutil.copy2(self.renderer_src, anim_renderer)
        shutil.copy2(self.manim_cfg_src, anim_cfg)

        try:
            quality_flag = quality if quality.startswith("-") else f"-{quality}"
            cmd = [
                sys.executable, "-m", "manim", "render",
                quality_flag,
                "manifest_scene.py", "ManifestDrivenScene",
            ]
            env = os.environ.copy()
            old_pythonpath = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                str(self.project_root)
                if not old_pythonpath
                else f"{self.project_root}{os.pathsep}{old_pythonpath}"
            )
            env["MANIM_CACHE_DISABLE"] = "1"
            env["MD2VIDEO_PLAN_PATH"] = str(plan_path.resolve())
            env["MD2VIDEO_EXECUTION_ASSETS_PATH"] = str(assets_path.resolve())
            env["MD2VIDEO_TIMELINE_PATH"] = str(timeline_path.resolve())
            env.pop("MD2VIDEO_ARTIFACTS_DIR", None)

            render_start = time.time()
            proc = subprocess.run(
                cmd,
                cwd=str(anim_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode != 0:
                stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
                if stderr_tail:
                    print("  Render stderr (last 20 lines):")
                    for line in stderr_tail.splitlines():
                        print(f"    {line}")
                raise RuntimeError(
                    f"Manim rendering failed (exit {proc.returncode})"
                )

            print("  Render OK")
            self._validate_timeline(timeline_path, render_start, plan_path)

            video_path = self._find_rendered_video(anim_dir)
            if not video_path:
                raise FileNotFoundError("No rendered video found")

            return {
                "video_path": str(video_path),
                "timeline_path": str(timeline_path),
                "provider": self.provider_name,
                "render_dir": str(anim_dir),
            }

        finally:
            if anim_renderer.exists():
                anim_renderer.unlink()
            if anim_cfg.exists():
                anim_cfg.unlink()

    @staticmethod
    def _required_value(input_data: Dict[str, Any], key: str) -> str:
        value = input_data.get(key)
        if not value:
            raise ValueError(f"ManimRenderTool requires input field: {key}")
        return str(value)

    @classmethod
    def _required_path(cls, input_data: Dict[str, Any], key: str) -> Path:
        return Path(cls._required_value(input_data, key))

    @staticmethod
    def _validate_timeline(timeline_path: Path, render_start: float, plan_path: Path) -> None:
        if not timeline_path.exists():
            raise FileNotFoundError(f"Timeline not generated: {timeline_path}")
        if timeline_path.stat().st_mtime < render_start - 1.0:
            raise RuntimeError(f"Timeline is stale: {timeline_path}")

        try:
            data = json.loads(timeline_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Timeline is not valid JSON: {timeline_path}") from exc

        required_keys = {"text", "markers", "shots"}
        if not isinstance(data, dict) or not required_keys.issubset(data):
            raise RuntimeError(
                f"Timeline missing required keys {sorted(required_keys)}: {timeline_path}"
            )

        for key in required_keys:
            if not isinstance(data[key], list):
                raise RuntimeError(f"Timeline field must be a list: {key}")

        plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
        ManimRenderTool._validate_marker_timing(data["markers"], plan)

        required_shots = {
            shot.id: set(shot.segment_ids)
            for scene in plan.scenes
            for shot in scene.shots
        }
        if not required_shots:
            return

        timeline_shots: dict[str, set[str]] = {}
        for item in data["shots"]:
            if not isinstance(item, dict):
                continue
            shot_id = item.get("shot_id")
            if not isinstance(shot_id, str) or not shot_id:
                continue
            segment_ids = item.get("segment_ids", [])
            if not isinstance(segment_ids, list):
                raise RuntimeError(
                    f"Timeline shot field must be a list: segment_ids for {shot_id}"
                )
            if shot_id in required_shots:
                ManimRenderTool._validate_shot_timing(item, shot_id)
            timeline_shots.setdefault(shot_id, set()).update(
                sid for sid in segment_ids if isinstance(sid, str)
            )

        missing_shots = sorted(set(required_shots) - set(timeline_shots))
        if missing_shots:
            raise RuntimeError(f"Timeline missing plan shots: {missing_shots}")

        missing_segments = {
            shot_id: sorted(required_segments - timeline_shots[shot_id])
            for shot_id, required_segments in required_shots.items()
            if required_segments - timeline_shots[shot_id]
        }
        if missing_segments:
            details = "; ".join(
                f"{shot_id}: {segment_ids}"
                for shot_id, segment_ids in sorted(missing_segments.items())
            )
            raise RuntimeError(f"Timeline missing plan segments: {details}")

    @staticmethod
    def _validate_marker_timing(markers: list, plan: PlanManifest) -> None:
        required_marker_ids = sorted(
            str(cue.get("id", ""))
            for scene in plan.scenes
            for shot in scene.shots
            for cue in shot.cues
            if cue.get("cue_type") in ("marker_music", "marker_image")
            and cue.get("id")
        )
        if not required_marker_ids:
            return

        markers_by_id: dict[str, dict] = {}
        for marker in markers:
            if not isinstance(marker, dict):
                continue
            marker_ids = (
                marker.get("id"),
                marker.get("segment_id"),
            )
            for marker_id in marker_ids:
                if isinstance(marker_id, str) and marker_id in required_marker_ids:
                    markers_by_id[marker_id] = marker

        missing_markers = [
            marker_id
            for marker_id in required_marker_ids
            if marker_id not in markers_by_id
        ]
        if missing_markers:
            raise RuntimeError(f"Timeline missing marker entries: {missing_markers}")

        invalid_times = []
        for marker_id in required_marker_ids:
            marker = markers_by_id[marker_id]
            try:
                marker_time = float(marker["time"])
            except (KeyError, TypeError, ValueError):
                invalid_times.append(marker_id)
                continue
            if not math.isfinite(marker_time):
                invalid_times.append(marker_id)

        if invalid_times:
            raise RuntimeError(
                f"Timeline marker time must be numeric and finite: {invalid_times}"
            )

    @staticmethod
    def _validate_shot_timing(item: dict, shot_id: str) -> None:
        if "start" not in item or "end" not in item:
            raise RuntimeError(f"Timeline shot missing start/end: {shot_id}")
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Timeline shot start/end must be numeric: {shot_id}") from exc
        if not math.isfinite(start) or not math.isfinite(end):
            raise RuntimeError(f"Timeline shot start/end must be finite: {shot_id}")
        if end < start:
            raise RuntimeError(f"Timeline shot end before start: {shot_id}")

    @staticmethod
    def _find_rendered_video(anim_dir: Path) -> Path | None:
        media_dir = anim_dir / "media" / "videos"
        if not media_dir.exists():
            media_dir = anim_dir / "media"

        mp4s = list(media_dir.rglob("*.mp4")) if media_dir.exists() else []
        if not mp4s:
            return None

        scene_mp4s = [path for path in mp4s if "ManifestDrivenScene" in str(path)]
        if scene_mp4s:
            return max(scene_mp4s, key=lambda path: path.stat().st_mtime)

        return max(mp4s, key=lambda path: path.stat().st_mtime)
