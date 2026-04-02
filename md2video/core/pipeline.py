"""
Pipeline - 框架核心编排器。

流程: Parser → Planner → TTS (pre-compute) → Render (Manim) → Assembler (FFmpeg)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from md2video.manifest.schema import (
    PlanManifest, ResultManifest, SegmentPlan,
    SegmentResult, AudioResult, SceneResult, ShotResult, VisualResult,
)
from md2video.parser.md_parser import parse_to_plan_manifest
from md2video.core.planner.rule_planner import RulePlanner, denormalize_scenes_to_segments
from md2video.tools.tts.edge_tts import EdgeTTSTool
from md2video.config import ARTIFACTS_DIR, DEFAULT_VOICE, DEFAULT_SPEED


class Pipeline:
    def __init__(self, artifacts_dir: str | Path = None, voice: str = None, speed: float = None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice or DEFAULT_VOICE
        self.speed = speed or DEFAULT_SPEED
        self.tts_tool = EdgeTTSTool(cache_dir=self.artifacts_dir / "tts", voice=self.voice)
        self.planner = RulePlanner()

    def run(self, md_path: str, output_path: str) -> Path:
        md_path = Path(md_path)
        output_path = Path(output_path)

        # 1. Parse → Plan Manifest
        print("[1/5] Parsing markdown...")
        plan = parse_to_plan_manifest(str(md_path))
        scenes = self.planner.plan(plan.segments)
        denormalize_scenes_to_segments(plan.segments, scenes)
        plan.scenes = scenes
        plan_path = self.artifacts_dir / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        print(f"  Plan: {len(plan.segments)} segments, {len(scenes)} scenes")

        # 2. TTS pre-compute → fill Result Manifest
        print("[2/5] Pre-computing TTS...")
        result = ResultManifest()
        current_time = 0.0
        for seg in plan.segments:
            if seg.audio_request:
                audio = self.tts_tool.synthesize(
                    text=seg.text,
                    voice=seg.audio_request.voice,
                    speed=seg.audio_request.speed,
                    fmt=seg.audio_request.format,
                )
                dur = audio["duration"]
                result.segments.append(SegmentResult(
                    id=seg.id,
                    audio=AudioResult(
                        path=audio["path"],
                        duration=audio["duration"],
                        provider=audio["provider"],
                        cache_key=audio["cache_key"],
                    ),
                    start=current_time,
                    end=current_time + dur,
                ))
                current_time += dur
            else:
                # marker: 零时长，继承当前时间
                result.segments.append(SegmentResult(
                    id=seg.id,
                    start=current_time,
                    end=current_time,
                ))

        print(f"  TTS: {sum(1 for s in result.segments if s.audio)} audio segments")

        # 构建 SceneResult
        result.scenes = self._build_scene_results(plan.scenes, result.segments)

        # 保存 Result Manifest
        result_path = self.artifacts_dir / "result.json"
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        # 3. Render (Manim)
        print("[3/5] Rendering video...")
        # 复制 renderer 到 anim/ 目录作为临时入口
        anim_dir = md_path.parent
        renderer_src = Path(__file__).parent.parent / "tools" / "render" / "manim_renderer.py"
        anim_renderer = anim_dir / "manifest_scene.py"

        # 确保 manim.cfg 存在（竖屏 480x854 配置）
        manim_cfg_src = Path(__file__).parent.parent / "tools" / "render" / "manim.cfg"
        if not (anim_dir / "manim.cfg").exists():
            shutil.copy2(manim_cfg_src, anim_dir / "manim.cfg")

        # 复制 scene 文件
        shutil.copy2(renderer_src, anim_renderer)

        # 复制 md2video 包使 manim 可以 import
        # 设置 PYTHONPATH
        project_root = Path(__file__).parent.parent.parent
        env_pythonpath = str(project_root)

        try:
            cmd = [
                sys.executable, "-m", "manim", "render",
                "-ql",
                "manifest_scene.py", "ManifestDrivenScene",
            ]
            env = {"PYTHONPATH": env_pythonpath, "MANIM_CACHE_DISABLE": "1"}
            # 继承环境变量
            import os
            for key in ["PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"]:
                if key in os.environ:
                    env[key] = os.environ[key]

            proc = subprocess.run(cmd, cwd=str(anim_dir), env=env,
                                  capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                print(f"  Render stderr (last 20 lines):")
                for line in proc.stderr.strip().split("\n")[-20:]:
                    print(f"    {line}")
                raise RuntimeError(f"Manim rendering failed (exit {proc.returncode})")

            print(f"  Render OK")

            # 4. 找到渲染输出的视频
            print("[4/5] Finding rendered video...")
            video_path = self._find_rendered_video(anim_dir)
            if not video_path:
                raise FileNotFoundError("No rendered video found")
            print(f"  Video: {video_path}")

            # 5. Assemble
            print("[5/5] Assembling final video...")
            from md2video.assembler.ffmpeg_assembler import FFmpegAssembler
            assembler = FFmpegAssembler(plan, result, video_path, output_path,
                                        md_dir=md_path.parent,
                                        timeline_path=anim_dir / "timeline.json")
            assembler.assemble()
            print(f"  Output: {output_path}")

        finally:
            # 清理临时文件
            if anim_renderer.exists():
                anim_renderer.unlink()
            anim_cfg = anim_dir / "manim.cfg"
            if anim_cfg.exists():
                anim_cfg.unlink()

        return output_path

    def _find_rendered_video(self, anim_dir: Path) -> Path | None:
        """在 media/ 目录中找到最新渲染的 .mp4。"""
        media_dir = anim_dir / "media" / "videos"
        if not media_dir.exists():
            media_dir = anim_dir / "media"

        mp4s = list(media_dir.rglob("*.mp4"))
        if not mp4s:
            return None

        # 优先找 ManifestDrivenScene 输出
        scene_mp4s = [p for p in mp4s if "ManifestDrivenScene" in str(p)]
        if scene_mp4s:
            return max(scene_mp4s, key=lambda p: p.stat().st_mtime)

        return max(mp4s, key=lambda p: p.stat().st_mtime)

    def _build_scene_results(self, scene_plans, segment_results):
        """从 segment 的 start/end 累加出 shot → scene 的 start/end。"""
        result_map = {sr.id: sr for sr in segment_results}
        scene_results = []
        for sp in scene_plans:
            if not sp.shots:
                continue
            shot_results = []
            for shot_plan in sp.shots:
                if not shot_plan.segment_ids:
                    continue
                starts = [result_map[sid].start for sid in shot_plan.segment_ids if sid in result_map]
                ends = [result_map[sid].end for sid in shot_plan.segment_ids if sid in result_map]
                if starts and ends:
                    shot_results.append(ShotResult(
                        id=shot_plan.id,
                        segment_ids=shot_plan.segment_ids,
                        start=min(starts),
                        end=max(ends),
                        visual=VisualResult(),
                    ))
            if shot_results:
                scene_results.append(SceneResult(
                    id=sp.id,
                    shots=shot_results,
                    start=min(sr.start for sr in shot_results),
                    end=max(sr.end for sr in shot_results),
                ))
        return scene_results
