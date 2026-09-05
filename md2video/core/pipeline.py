"""
Pipeline - framework/runtime orchestration.

Runtime artifacts:
- plan.json: intent and target constraints.
- execution-assets.json: material facts produced by tools.
- timeline.json: renderer timing facts.
- result.json: final delivery summary written after assemble.
"""
from __future__ import annotations

from pathlib import Path

from md2video.config import (
    ARTIFACTS_DIR,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    load_pexels_config,
    load_planner_config,
    load_tool_config,
)
from md2video.core.planner.rule_planner import (
    RulePlanner,
    denormalize_scenes_to_segments,
    renderable_segments,
)
from md2video.layout import create_default_layout_registry
from md2video.manifest.schema import (
    AudioAsset,
    ExecutionAssets,
    FinalResultManifest,
    PlanManifest,
    ResultManifest,
    SceneResult,
    SegmentResult,
    ShotResult,
    VisualAsset,
    VisualResult,
    result_manifest_from_execution_assets,
)
from md2video.parser.md_parser import parse_to_plan_manifest
from md2video.tools.registry import ToolRegistry
from md2video.tools.render.manim_renderer_inputs import validate_renderer_visual_types
from md2video.tools.tts.edge_tts import EdgeTTSTool


class Pipeline:
    def __init__(self, artifacts_dir=None, voice=None, speed=None, planner=None,
                 tool_config=None, layout_registry=None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._warnings: list[str] = []
        self._voice_override = voice is not None
        self._speed_override = speed is not None
        self.voice = voice or DEFAULT_VOICE
        self.speed = speed or DEFAULT_SPEED
        self.planner = self._create_planner(planner)

        self.tool_config = tool_config or load_tool_config()
        self.layout_registry = layout_registry or create_default_layout_registry()
        self.registry = ToolRegistry()
        self._register_default_tools()

    def _register_default_tools(self):
        # TTS
        tts_tool = EdgeTTSTool(cache_dir=self.artifacts_dir / "tts", voice=self.voice)
        self.registry.register("tts", tts_tool)

        # Render (Manim)
        from md2video.tools.render.manim_tool import ManimRenderTool
        self.registry.register("render", ManimRenderTool())

        # Local image provider is the default no-key verification path.
        from md2video.tools.image.local_image_tool import LocalImageTool
        self.registry.register("stock_image", LocalImageTool())

        # Pexels is optional and registered only when a key is configured.
        pexels_cfg = load_pexels_config()
        if pexels_cfg.api_key:
            from md2video.tools.image.pexels_image_tool import PexelsImageTool
            self.registry.register("stock_image", PexelsImageTool(
                api_key=pexels_cfg.api_key,
                cache_dir=self.artifacts_dir / "images",
            ))

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

        print("[1/5] Parsing markdown...")
        plan = self._load_or_build_plan_from_markdown(md_path)
        return self._execute_plan(
            plan=plan,
            output_path=output_path,
            base_dir=md_path.parent,
            render_dir=self.artifacts_dir,
        )

    def run_plan(self, plan_path: str, output_path: str) -> Path:
        plan_path = Path(plan_path)
        output_path = Path(output_path)

        print("[1/5] Loading plan manifest...")
        plan = self._load_plan_from_json(plan_path)
        return self._execute_plan(
            plan=plan,
            output_path=output_path,
            base_dir=plan_path.parent,
            render_dir=self.artifacts_dir,
        )

    def _load_or_build_plan_from_markdown(self, md_path: Path) -> PlanManifest:
        plan = parse_to_plan_manifest(str(md_path))
        scenes = self.planner.plan(plan.segments)
        plan.segments = renderable_segments(plan.segments)
        denormalize_scenes_to_segments(plan.segments, scenes)
        plan.scenes = scenes
        print(f"  Plan: {len(plan.segments)} segments, {len(scenes)} scenes")
        return plan

    def _load_plan_from_json(self, plan_path: Path) -> PlanManifest:
        plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
        print(f"  Plan: {len(plan.segments)} segments, {len(plan.scenes)} scenes")
        return plan

    def _execute_plan(
        self,
        plan: PlanManifest,
        output_path: Path,
        base_dir: Path,
        render_dir: Path,
    ) -> Path:
        self._warnings = []
        self._validate_plan_layouts(plan)
        self._validate_plan_visual_types(plan)
        plan_path = self._write_plan_manifest(plan)

        print("[2/5] Preparing execution assets...")
        assets = self._prepare_execution_assets(plan)
        result = result_manifest_from_execution_assets(plan, assets)

        self._fill_target_durations(plan.segments, result.segments)
        plan_path = self._write_plan_manifest(plan)
        result = result_manifest_from_execution_assets(plan, assets)

        self._dispatch_visual_tools(
            plan,
            result,
            base_dir=base_dir,
            execution_assets=assets,
            validate_layouts=False,
        )

        assets_path = self._write_execution_assets(assets)
        result = result_manifest_from_execution_assets(plan, assets)

        print("[3/5] Rendering video...")
        render_tool = self.registry.get_tool("render", "manim")
        if not render_tool:
            raise ValueError("Render tool not registered: render/manim")
        timeline_path = render_dir / "timeline.json"
        render_output = render_tool.execute({
            "plan_path": str(plan_path),
            "execution_assets_path": str(assets_path),
            "timeline_path": str(timeline_path),
            "output_dir": str(render_dir),
            "timeout": 300,
        })
        video_path, timeline_path = self._validate_render_output(render_output, timeline_path)
        print(f"  Video: {video_path}")

        print("[4/5] Assembling final video...")
        from md2video.assembler.ffmpeg_assembler import FFmpegAssembler
        assembler = FFmpegAssembler(
            plan,
            result,
            video_path,
            output_path,
            md_dir=base_dir,
            timeline_path=timeline_path,
            execution_assets=assets,
        )
        assembler.assemble()
        print(f"  Output: {output_path}")

        self._write_final_result(
            output_path,
            plan_path,
            assets_path,
            timeline_path,
            assets,
            video_path=video_path,
            render_output=render_output,
        )
        return output_path

    @staticmethod
    def _validate_render_output(render_output, expected_timeline_path: Path) -> tuple[Path, Path]:
        if not isinstance(render_output, dict):
            raise RuntimeError("Render backend returned invalid output: expected dict")

        required_fields = ("video_path", "timeline_path", "provider", "render_dir")
        missing_fields = [
            field
            for field in required_fields
            if not str(render_output.get(field, "")).strip()
        ]
        if missing_fields:
            raise RuntimeError(
                f"Render backend returned invalid output: missing fields {missing_fields}"
            )

        provider = str(render_output["provider"])
        if provider != "manim":
            raise RuntimeError(
                f"Render backend returned unexpected provider: expected manim, got {provider}"
            )

        video_path = Path(str(render_output["video_path"]))
        timeline_path = Path(str(render_output["timeline_path"]))
        render_dir = Path(str(render_output["render_dir"]))
        if timeline_path.resolve() != expected_timeline_path.resolve():
            raise RuntimeError(
                "Render backend returned unexpected timeline_path: "
                f"expected {expected_timeline_path}, got {timeline_path}"
            )

        missing_artifacts = []
        if not video_path.is_file():
            missing_artifacts.append(f"video_path={video_path}")
        if not timeline_path.is_file():
            missing_artifacts.append(f"timeline_path={timeline_path}")
        if not render_dir.is_dir():
            missing_artifacts.append(f"render_dir={render_dir}")
        if missing_artifacts:
            raise RuntimeError(
                "Render backend returned missing artifacts: "
                + ", ".join(missing_artifacts)
            )

        return video_path, timeline_path

    def _prepare_execution_assets(self, plan: PlanManifest) -> ExecutionAssets:
        assets = ExecutionAssets()
        tts_tool = self.registry.get_tool("tts", "edge-tts")
        for segment in plan.segments:
            if not segment.audio_request or segment.segment_type in ("title_main", "title_sub"):
                continue
            audio = tts_tool.execute({
                "text": segment.text,
                "voice": self.voice if self._voice_override else segment.audio_request.voice,
                "speed": self.speed if self._speed_override else segment.audio_request.speed,
                "format": segment.audio_request.format,
            })
            audio_path = Path(audio["path"])
            assets.audio_assets.append(AudioAsset(
                segment_id=segment.id,
                path=str(audio_path.resolve()),
                duration=audio["duration"],
                provider=audio["provider"],
                cache_key=audio["cache_key"],
            ))

        print(f"  TTS: {len(assets.audio_assets)} audio assets")
        return assets

    def _write_plan_manifest(self, plan: PlanManifest) -> Path:
        path = self.artifacts_dir / "plan.json"
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _write_execution_assets(self, assets: ExecutionAssets) -> Path:
        path = self.artifacts_dir / "execution-assets.json"
        path.write_text(assets.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _write_final_result(
        self,
        output_path: Path,
        plan_path: Path,
        assets_path: Path,
        timeline_path: Path | None,
        assets: ExecutionAssets,
        video_path: Path | None = None,
        render_output: dict | None = None,
    ) -> Path:
        result_path = self.artifacts_dir / "result.json"
        artifact_index = {
            "plan": str(plan_path),
            "execution_assets": str(assets_path),
            "timeline": str(timeline_path) if timeline_path else "",
            "result": str(result_path),
        }
        if video_path:
            artifact_index["base_video"] = str(video_path)
        if render_output:
            artifact_index["render_dir"] = str(render_output.get("render_dir", ""))
            artifact_index["render_provider"] = str(render_output.get("provider", ""))

        final_result = FinalResultManifest(
            output_mp4=str(output_path),
            used_assets={
                "audio": [asset.model_dump() for asset in assets.audio_assets],
                "visual": [asset.model_dump() for asset in assets.visual_assets],
            },
            warnings=self._warnings,
            artifact_index=artifact_index,
        )
        result_path.write_text(final_result.model_dump_json(indent=2), encoding="utf-8")
        return result_path

    def _validate_plan_layouts(self, plan: PlanManifest) -> None:
        for scene in plan.scenes:
            try:
                self.layout_registry.compute(scene.layout_type, scene.layout_params)
            except Exception as exc:
                raise ValueError(
                    f"Invalid layout for scene {scene.id}: {exc}"
                ) from exc

    def _dispatch_visual_tools(
        self,
        plan,
        result,
        base_dir,
        execution_assets=None,
        validate_layouts=True,
    ):
        """Dispatch non-text visual tools for scenes that need material assets."""
        if validate_layouts:
            self._validate_plan_layouts(plan)
            self._validate_plan_visual_types(plan)
        for scene in plan.scenes:
            if scene.shots and scene.visual_type != "text_only":
                self._dispatch_visual_tool(
                    scene,
                    plan,
                    result,
                    base_dir=base_dir,
                    execution_assets=execution_assets,
                )
        return None

    def _dispatch_render(self, *args, **kwargs):
        raise RuntimeError(
            "_dispatch_render no longer renders. Use _dispatch_visual_tools() "
            "for visual providers and the render/manim tool for base rendering."
        )

    def _dispatch_visual_tool(self, scene_plan, plan, result, base_dir=None, execution_assets=None):
        visual_type = scene_plan.visual_type
        preferred = scene_plan.visual_params.get("preferred_provider")
        providers = self.tool_config.get_priority(visual_type)

        tried = set()
        if preferred and preferred != "_text_only":
            tried.add(preferred)
            tool = self.registry.get_tool(visual_type, preferred)
            if tool:
                try:
                    self._invoke_visual_tool(
                        tool,
                        scene_plan,
                        plan,
                        result,
                        base_dir=base_dir,
                        execution_assets=execution_assets,
                    )
                    return
                except Exception as exc:
                    warning = f"Tool {preferred} failed for scene {scene_plan.id}: {exc}"
                    self._warnings.append(warning)
                    print(f"  {warning}")
                    if self._is_strict_local_visual(scene_plan, preferred):
                        raise

        for provider in providers:
            if provider in tried or provider == "_text_only":
                continue
            tried.add(provider)
            tool = self.registry.get_tool(visual_type, provider)
            if tool:
                try:
                    self._invoke_visual_tool(
                        tool,
                        scene_plan,
                        plan,
                        result,
                        base_dir=base_dir,
                        execution_assets=execution_assets,
                    )
                    return
                except Exception as exc:
                    warning = f"Tool {provider} failed for scene {scene_plan.id}: {exc}"
                    self._warnings.append(warning)
                    print(f"  {warning}")
                    if self._is_strict_local_visual(scene_plan, provider):
                        raise

        warning = f"No tool available for {visual_type} in scene {scene_plan.id}"
        self._warnings.append(warning)
        print(f"  WARNING: {warning}")

    @staticmethod
    def _is_strict_local_visual(scene_plan, provider: str | None) -> bool:
        visual_params = scene_plan.visual_params or {}
        has_local_path = any(
            visual_params.get(key)
            for key in ("path", "src", "image_path")
        )
        return provider == "local" and has_local_path

    @staticmethod
    def _validate_plan_visual_types(plan: PlanManifest) -> None:
        validate_renderer_visual_types(plan)

    def _invoke_visual_tool(self, tool, scene_plan, plan, result, base_dir=None, execution_assets=None):
        seg_map = {segment.id: segment for segment in plan.segments}
        sr_map = {segment.id: segment for segment in result.segments}

        for shot_plan in scene_plan.shots:
            segments_data = []
            for sid in shot_plan.segment_ids:
                segment_plan = seg_map.get(sid)
                segment_result = sr_map.get(sid)
                segment_data = {
                    "id": sid,
                    "text": segment_plan.text if segment_plan else "",
                    "segment_type": segment_plan.segment_type if segment_plan else "",
                }
                if segment_result and segment_result.audio:
                    segment_data["audio"] = {
                        "path": segment_result.audio.path,
                        "duration": segment_result.audio.duration,
                    }
                else:
                    segment_data["audio"] = None
                segments_data.append(segment_data)

            output_dir = self.artifacts_dir / "visuals" / scene_plan.id
            output_dir.mkdir(parents=True, exist_ok=True)

            input_data = {
                "scene": {
                    "id": scene_plan.id,
                    "visual_type": scene_plan.visual_type,
                    "visual_params": scene_plan.visual_params,
                    "layout_type": scene_plan.layout_type,
                    "layout_params": scene_plan.layout_params,
                    "section_context": scene_plan.section_context,
                },
                "shot": {
                    "id": shot_plan.id,
                    "segment_ids": shot_plan.segment_ids,
                    "target_duration": sum(
                        (seg_map[sid].target_duration if sid in seg_map else 0.0)
                        for sid in shot_plan.segment_ids
                    ),
                    "cues": shot_plan.cues,
                },
                "segments": segments_data,
                "output_dir": str(output_dir),
            }
            if base_dir is not None:
                input_data["base_dir"] = str(base_dir)

            output = tool.execute(input_data)
            self._apply_visual_result(
                output,
                shot_plan.id,
                result,
                execution_assets=execution_assets,
            )

    def _apply_visual_result(self, tool_output, shot_plan_id, result, execution_assets=None):
        visuals = tool_output.get("visuals", [])
        matched = None
        for visual in visuals:
            if visual.get("shot_id") == shot_plan_id:
                matched = visual
                break
        if not matched and visuals:
            matched = visuals[0]
        if not matched:
            return

        for scene_result in result.scenes:
            for shot_result in scene_result.shots:
                if shot_result.id == shot_plan_id:
                    shot_result.visual = VisualResult(
                        path=matched.get("path", ""),
                        width=matched.get("width", 0),
                        height=matched.get("height", 0),
                        source=matched.get("source", "none"),
                    )
                    if execution_assets is not None:
                        self._upsert_visual_asset(execution_assets, shot_plan_id, matched)
                    return

    def _upsert_visual_asset(self, execution_assets, shot_plan_id, visual_data):
        asset = VisualAsset(
            shot_id=shot_plan_id,
            path=visual_data.get("path", ""),
            width=visual_data.get("width", 0),
            height=visual_data.get("height", 0),
            provider=visual_data.get("source", visual_data.get("provider", "none")),
            cache_key=visual_data.get("cache_key", ""),
            source_url=visual_data.get("source_url", ""),
        )
        execution_assets.visual_assets = [
            existing for existing in execution_assets.visual_assets
            if existing.shot_id != shot_plan_id
        ]
        execution_assets.visual_assets.append(asset)

    def _fill_target_durations(self, segment_plans, segment_results):
        seg_map = {segment.id: segment for segment in segment_results}
        for segment in segment_plans:
            result = seg_map.get(segment.id)
            if result is None:
                continue
            duration = result.end - result.start
            if duration <= 0 and result.audio:
                duration = result.audio.duration
            if duration > 0 or segment.target_duration <= 0:
                segment.target_duration = duration

    def _build_scene_results(self, scene_plans, segment_results):
        result_map = {segment.id: segment for segment in segment_results}
        scene_results = []
        for scene_plan in scene_plans:
            if not scene_plan.shots:
                continue
            shot_results = []
            for shot_plan in scene_plan.shots:
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
                    id=scene_plan.id,
                    shots=shot_results,
                    start=min(sr.start for sr in shot_results),
                    end=max(sr.end for sr in shot_results),
                ))
        return scene_results
