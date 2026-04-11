"""
Pipeline - 框架核心编排器。

流程: Parser → Planner → TTS (pre-compute) → Render (Manim) → Assembler (FFmpeg)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from md2video.manifest.schema import (
    PlanManifest, ResultManifest,
    SegmentResult, AudioResult, SceneResult, ShotResult, VisualResult,
)
from md2video.parser.md_parser import parse_to_plan_manifest
from md2video.core.planner.rule_planner import RulePlanner, denormalize_scenes_to_segments
from md2video.tools.tts.edge_tts import EdgeTTSTool
from md2video.tools.registry import ToolRegistry
from md2video.config import (
    ARTIFACTS_DIR, DEFAULT_VOICE, DEFAULT_SPEED,
    load_planner_config, load_tool_config,
)


class Pipeline:
    def __init__(self, artifacts_dir=None, voice=None, speed=None, planner=None,
                 tool_config=None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice or DEFAULT_VOICE
        self.speed = speed or DEFAULT_SPEED
        self.planner = self._create_planner(planner)

        # Tool infrastructure
        self.tool_config = tool_config or load_tool_config()
        self.registry = ToolRegistry()
        self._register_default_tools()

    def _register_default_tools(self):
        """注册内建工具。"""
        # TTS
        tts_tool = EdgeTTSTool(cache_dir=self.artifacts_dir / "tts", voice=self.voice)
        self.registry.register("tts", tts_tool)
        # Render (Manim)
        from md2video.tools.render.manim_tool import ManimRenderTool
        self.registry.register("text_only", ManimRenderTool())

    @staticmethod
    def _create_planner(planner: str | None) -> RulePlanner | "LlmPlanner":
        cfg = load_planner_config()
        choice = planner or cfg.default
        if choice == "llm" and (cfg.api_key or cfg.base_url):
            try:
                from md2video.core.planner.llm_planner import LlmPlanner
                print(f"  Planner: LLM ({cfg.model})")
                return LlmPlanner(model=cfg.model, api_key=cfg.api_key, base_url=cfg.base_url)
            except ImportError:
                print("  Planner: pydantic-ai not installed, falling back to Rule")
        print("  Planner: Rule")
        return RulePlanner()

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

        tts_tool = self.registry.get_tool("tts", "edge-tts")
        for seg in plan.segments:
            if seg.audio_request:
                audio = tts_tool.execute({
                    "text": seg.text,
                    "voice": seg.audio_request.voice,
                    "speed": seg.audio_request.speed,
                    "format": seg.audio_request.format,
                })
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
                result.segments.append(SegmentResult(
                    id=seg.id,
                    start=current_time,
                    end=current_time,
                ))

        print(f"  TTS: {sum(1 for s in result.segments if s.audio)} audio segments")

        # 填充 target_duration 并重新保存 plan.json
        self._fill_target_durations(plan.scenes, result.segments)
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        # 构建 SceneResult
        result.scenes = self._build_scene_results(plan.scenes, result.segments)

        # 保存 Result Manifest
        result_path = self.artifacts_dir / "result.json"
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        # 3. Render — 按 visual_type 分发
        print("[3/5] Rendering video...")
        video_path, timeline_path = self._dispatch_render(plan, result, md_path)
        print(f"  Video: {video_path}")

        # 4. Assemble
        print("[4/5] Assembling final video...")
        from md2video.assembler.ffmpeg_assembler import FFmpegAssembler
        assembler = FFmpegAssembler(
            plan, result, video_path, output_path,
            md_dir=md_path.parent,
            timeline_path=timeline_path,
        )
        assembler.assemble()
        print(f"  Output: {output_path}")

        return output_path

    def _dispatch_render(self, plan, result, md_path):
        """按 visual_type 分发渲染任务。Phase 3: 全部走 Manim 批量渲染。"""
        visual_types = set(sc.visual_type for sc in plan.scenes if sc.shots)

        # Phase 3: 只有 text_only，直接走 Manim 批量渲染
        if visual_types == {"text_only"} or not visual_types:
            return self._render_manim_batch(md_path)

        # 未来: 多 visual_type 分发（Phase 4）
        for vt in visual_types:
            self._dispatch_tool(vt, plan, result, md_path)
        # Phase 3 兜底
        return self._render_manim_batch(md_path)

    def _dispatch_tool(self, visual_type, plan, result, md_path):
        """按优先级序列尝试 provider，首个成功即采用。"""
        providers = self.tool_config.get_priority(visual_type)

        # 检查 preferred_provider
        preferred = None
        for sc in plan.scenes:
            if sc.visual_type == visual_type and "preferred_provider" in sc.visual_params:
                preferred = sc.visual_params["preferred_provider"]
                break

        tried = set()
        if preferred and preferred not in tried:
            tried.add(preferred)
            tool = self.registry.get_tool(visual_type, preferred)
            if tool:
                try:
                    return self._invoke_tool(tool, plan, result, md_path)
                except Exception as e:
                    print(f"  Tool {preferred} failed: {e}")

        for provider in providers:
            if provider in tried:
                continue
            if provider == "_text_only":
                tool = self.registry.get_tool("text_only", "manim")
                if tool:
                    return self._invoke_tool(tool, plan, result, md_path)
                continue

            tried.add(provider)
            tool = self.registry.get_tool(visual_type, provider)
            if tool:
                try:
                    return self._invoke_tool(tool, plan, result, md_path)
                except Exception as e:
                    print(f"  Tool {provider} failed: {e}")

        raise RuntimeError(f"All tools failed for visual_type={visual_type}")

    def _invoke_tool(self, tool, plan, result, md_path):
        """调用工具，处理不同执行模式。"""
        if tool.provider_name == "manim" and tool.tool_type == "render":
            return self._render_manim_batch(md_path)
        raise NotImplementedError(f"Tool {tool.provider_name} execution not yet supported")

    def _render_manim_batch(self, md_path):
        """Manim 批量渲染 (text_only scenes)。"""
        anim_dir = md_path.parent
        renderer_src = Path(__file__).parent.parent / "tools" / "render" / "manim_renderer.py"
        anim_renderer = anim_dir / "manifest_scene.py"

        manim_cfg_src = Path(__file__).parent.parent / "tools" / "render" / "manim.cfg"
        if not (anim_dir / "manim.cfg").exists():
            shutil.copy2(manim_cfg_src, anim_dir / "manim.cfg")

        shutil.copy2(renderer_src, anim_renderer)

        project_root = Path(__file__).parent.parent.parent
        env_pythonpath = str(project_root)

        try:
            cmd = [
                sys.executable, "-m", "manim", "render",
                "-ql",
                "manifest_scene.py", "ManifestDrivenScene",
            ]
            env = {"PYTHONPATH": env_pythonpath, "MANIM_CACHE_DISABLE": "1"}
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

            video_path = self._find_rendered_video(anim_dir)
            if not video_path:
                raise FileNotFoundError("No rendered video found")

            return video_path, anim_dir / "timeline.json"

        finally:
            if anim_renderer.exists():
                anim_renderer.unlink()
            anim_cfg = anim_dir / "manim.cfg"
            if anim_cfg.exists():
                anim_cfg.unlink()

    def _find_rendered_video(self, anim_dir: Path) -> Path | None:
        """在 media/ 目录中找到最新渲染的 .mp4。"""
        media_dir = anim_dir / "media" / "videos"
        if not media_dir.exists():
            media_dir = anim_dir / "media"

        mp4s = list(media_dir.rglob("*.mp4"))
        if not mp4s:
            return None

        scene_mp4s = [p for p in mp4s if "ManifestDrivenScene" in str(p)]
        if scene_mp4s:
            return max(scene_mp4s, key=lambda p: p.stat().st_mtime)

        return max(mp4s, key=lambda p: p.stat().st_mtime)

    def _fill_target_durations(self, scene_plans, segment_results):
        """填充 ShotPlan.target_duration（TTS 时长之和）。"""
        seg_map = {sr.id: sr for sr in segment_results}
        for sp in scene_plans:
            for shot in sp.shots:
                starts = [seg_map[sid].start for sid in shot.segment_ids if sid in seg_map]
                ends = [seg_map[sid].end for sid in shot.segment_ids if sid in seg_map]
                if starts and ends:
                    shot.target_duration = max(ends) - min(starts)

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
