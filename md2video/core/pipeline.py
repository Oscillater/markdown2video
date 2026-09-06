"""
Pipeline - framework/runtime orchestration.

Runtime artifacts（每次 run 一个独立目录 artifacts/runs/<run_id>/，永不
覆盖、永不删除，归属与失效判断只靠 run_id 与命名）：
- plan.json: intent and target constraints.
- execution-assets.json: material facts produced by tools.
- timeline.json: renderer timing facts.
- result.json: final delivery summary written after assemble.
- manifest_viewer.html: 一次 run 的紧凑静态检查页。
"""
from __future__ import annotations

import json
from pathlib import Path

from md2video.config import (
    ARTIFACTS_DIR,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    load_pexels_config,
    load_planner_config,
    load_tool_config,
)
from md2video.core.multi_backend import RenderGroup, plan_render_groups
from md2video.core.planner.rule_planner import (
    RulePlanner,
    renderable_segments,
)
from md2video.inspect.runs import create_run_dir, new_run_id
from md2video.inspect.viewer import VIEWER_FILENAME, build_run_view, write_manifest_viewer
from md2video.layout import create_default_layout_registry
from md2video.layout.constraints import load_constraint_modules
from md2video.manifest.migration import load_plan_manifest_json
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
from md2video.style.packs import active_pack
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
        # 显式加载外部 layout 约束模块（env MD2VIDEO_LAYOUT_CONSTRAINTS）；
        # 导入/注册失败在这里 fail fast，不带病开渲。
        load_constraint_modules()
        self.registry = ToolRegistry()
        self._register_default_tools()
        # 本次 run 的目录与 id（_open_run_dir 赋值）；产物只增不删
        self.run_id = ""
        self.run_dir: Path | None = None

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
        )

    def _open_run_dir(self) -> Path:
        """创建本次 run 的独立目录 artifacts/runs/<run_id>/（绝不覆盖）。"""
        runs_root = self.artifacts_dir / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        for _ in range(5):
            run_id = new_run_id()
            try:
                run_dir = create_run_dir(runs_root, run_id)
            except FileExistsError:
                continue
            self.run_id = run_id
            self.run_dir = run_dir
            print(f"  Run dir: {run_dir}")
            return run_dir
        raise RuntimeError("Could not create a unique run directory under runs/")

    def _load_or_build_plan_from_markdown(self, md_path: Path) -> PlanManifest:
        plan = parse_to_plan_manifest(str(md_path))
        scenes = self.planner.plan(plan.segments)
        plan.segments = renderable_segments(plan.segments)
        plan.scenes = scenes
        print(f"  Plan: {len(plan.segments)} segments, {len(scenes)} scenes")
        return plan

    def _load_plan_from_json(self, plan_path: Path) -> PlanManifest:
        plan, warnings = load_plan_manifest_json(plan_path.read_text(encoding="utf-8"))
        for warning in warnings:
            print(f"  Plan migration: {warning}")
        print(f"  Plan: {len(plan.segments)} segments, {len(plan.scenes)} scenes")
        return plan

    def _execute_plan(
        self,
        plan: PlanManifest,
        output_path: Path,
        base_dir: Path,
    ) -> Path:
        self._warnings = []
        run_dir = self._open_run_dir()
        try:
            return self._run_plan_steps(plan, output_path, base_dir, run_dir)
        except Exception as exc:
            self._write_failed_result(run_dir, exc)
            raise

    def _run_plan_steps(
        self,
        plan: PlanManifest,
        output_path: Path,
        base_dir: Path,
        run_dir: Path,
    ) -> Path:
        self._validate_plan_layouts(plan)
        self._validate_plan_visual_types(plan)
        plan_path = self._write_plan_manifest(plan, run_dir)

        print("[2/5] Preparing execution assets...")
        assets = self._prepare_execution_assets(plan)
        result = result_manifest_from_execution_assets(plan, assets)

        self._dispatch_visual_tools(
            plan,
            result,
            base_dir=base_dir,
            execution_assets=assets,
            validate_layouts=False,
        )

        assets_path = self._write_execution_assets(assets, run_dir)
        result = result_manifest_from_execution_assets(plan, assets)

        print("[3/5] Rendering video...")
        render_backend = self.tool_config.render_backend
        # 按 scene 的 render_backend 把 scene 序列切成极大同后端组；
        # 要求的后端没注册就在开渲前 fail fast，不带病渲染。
        groups = plan_render_groups(plan, render_backend)
        missing_backends = []
        for group in groups:
            if not self.registry.get_tool("render", group.backend):
                missing_backends.append(group.backend)
        if missing_backends:
            raise ValueError(
                "Render tool not registered: "
                + ", ".join(
                    f"render/{backend}" for backend in dict.fromkeys(missing_backends)
                )
            )

        if len(groups) <= 1:
            render_output, video_path, timeline_path = self._render_single_group(
                plan, assets, run_dir, groups[0] if groups else RenderGroup(backend=render_backend),
            )
        else:
            render_output, video_path, timeline_path = self._render_backend_groups(
                plan, assets, assets_path, run_dir, groups,
            )
        render_warnings = render_output.get("warnings") or []
        self._warnings.extend(str(warning) for warning in render_warnings)
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

        timeline_data = json.loads(timeline_path.read_text(encoding="utf-8"))
        self._write_final_result(
            run_dir=run_dir,
            output_path=output_path,
            plan=plan,
            assets=assets,
            timeline_data=timeline_data,
            plan_path=plan_path,
            assets_path=assets_path,
            timeline_path=timeline_path,
            video_path=video_path,
            render_output=render_output,
        )
        return output_path

    def _render_single_group(
        self,
        plan: PlanManifest,
        assets: ExecutionAssets,
        run_dir: Path,
        group: "RenderGroup",
    ) -> tuple[dict, Path, Path]:
        """单组路径（现有行为，逐帧不变）：一次渲染调用产出底片与 timeline。"""
        render_tool = self.registry.get_tool("render", group.backend)
        timeline_path = run_dir / "timeline.json"
        render_output = render_tool.execute({
            "plan_path": str(run_dir / "plan.json"),
            "execution_assets_path": str(run_dir / "execution-assets.json"),
            "timeline_path": str(timeline_path),
            "output_dir": str(run_dir),
            "timeout": 300,
        })
        video_path, timeline_path = self._validate_render_output(
            render_output, timeline_path, expected_provider=group.backend,
        )
        return render_output, video_path, timeline_path

    def _render_backend_groups(
        self,
        plan: PlanManifest,
        assets: ExecutionAssets,
        assets_path: Path,
        run_dir: Path,
        groups: list["RenderGroup"],
    ) -> tuple[dict, Path, Path]:
        """多组路径：切片渲染 → 局部 timeline 前缀偏移合并 → 底片拼接。

        每组独立调用渲染后端（组边界即引擎切换，渲染器内部跨 shot 状态
        清零）；合并后的 timeline 对完整 plan 重过全局时间不变量闸门。
        """
        from md2video.core.multi_backend import (
            check_merged_timeline,
            concat_group_videos,
            merge_group_timelines,
            slice_plan,
        )

        groups_root = run_dir / "groups"
        local_timelines: list[dict] = []
        group_videos: list[Path] = []
        all_warnings: list[str] = []
        for index, group in enumerate(groups):
            group_dir = groups_root / f"{index:02d}_{group.backend}"
            group_dir.mkdir(parents=True, exist_ok=True)
            slice = slice_plan(plan, group.scenes)
            slice_path = group_dir / "plan.json"
            slice_path.write_text(slice.model_dump_json(indent=2), encoding="utf-8")
            timeline_path = group_dir / "timeline.json"
            render_tool = self.registry.get_tool("render", group.backend)
            render_output = render_tool.execute({
                "plan_path": str(slice_path),
                "execution_assets_path": str(assets_path),
                "timeline_path": str(timeline_path),
                "output_dir": str(group_dir),
                "timeout": 300,
            })
            video_path, timeline_path = self._validate_render_output(
                render_output, timeline_path, expected_provider=group.backend,
            )
            local_timelines.append(
                json.loads(timeline_path.read_text(encoding="utf-8"))
            )
            group_videos.append(video_path)
            all_warnings.extend(str(w) for w in render_output.get("warnings") or [])
            print(f"  Group {index}: {group.backend} ({len(group.scenes)} scenes)")

        merged = merge_group_timelines(local_timelines)
        merged_path = run_dir / "timeline.json"
        merged_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        check_merged_timeline(plan, assets, merged)

        concat_path = run_dir / "base_video.mp4"
        concat_group_videos(group_videos, concat_path)

        render_output = {
            "render_dir": str(groups_root),
            "provider": "+".join(group.backend for group in groups),
            "warnings": all_warnings,
        }
        return render_output, concat_path, merged_path

    @staticmethod
    def _validate_render_output(
        render_output,
        expected_timeline_path: Path,
        expected_provider: str,
    ) -> tuple[Path, Path]:
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
        if provider != expected_provider:
            raise RuntimeError(
                "Render backend returned unexpected provider: "
                f"expected {expected_provider}, got {provider}"
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

    def _write_plan_manifest(self, plan: PlanManifest, run_dir: Path) -> Path:
        path = Path(run_dir) / "plan.json"
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _write_execution_assets(self, assets: ExecutionAssets, run_dir: Path) -> Path:
        path = Path(run_dir) / "execution-assets.json"
        path.write_text(assets.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _write_final_result(
        self,
        run_dir: Path,
        output_path: Path,
        plan: PlanManifest,
        assets: ExecutionAssets,
        timeline_data: dict | None,
        plan_path: Path,
        assets_path: Path,
        timeline_path: Path | None,
        video_path: Path | None = None,
        render_output: dict | None = None,
    ) -> Path:
        viewer_path = Path(run_dir) / VIEWER_FILENAME
        artifact_index = {
            "plan": str(plan_path),
            "execution_assets": str(assets_path),
            "timeline": str(timeline_path) if timeline_path else "",
            "result": str(Path(run_dir) / "result.json"),
            "manifest_viewer": str(viewer_path),
        }
        if video_path:
            artifact_index["base_video"] = str(video_path)
        if render_output:
            artifact_index["render_dir"] = str(render_output.get("render_dir", ""))
            artifact_index["render_provider"] = str(render_output.get("provider", ""))

        # 风格降级（请求的 pack 不认识）是 run 级 warning，进 result 供检查页展示
        style_requested, style_pack = active_pack()
        warnings = list(self._warnings)
        if style_pack.id != style_requested:
            warnings.append(
                f"Style pack {style_requested!r} not found; "
                f"falling back to {style_pack.id!r}"
            )

        final_result = FinalResultManifest(
            run_id=self.run_id,
            status="completed",
            output_mp4=str(output_path),
            used_assets={
                "audio": [asset.model_dump() for asset in assets.audio_assets],
                "visual": [asset.model_dump() for asset in assets.visual_assets],
            },
            warnings=warnings,
            artifact_index=artifact_index,
        )

        # 检查页内嵌 result 摘要（含指向自己的 artifact index），先落盘再写 result.json
        view = build_run_view(
            run_id=self.run_id,
            plan=plan,
            assets=assets,
            timeline_data=timeline_data,
            final_result=final_result,
            style_pack=style_pack,
            style_requested=style_requested,
        )
        write_manifest_viewer(run_dir, view=view)
        result_path = Path(run_dir) / "result.json"
        result_path.write_text(final_result.model_dump_json(indent=2), encoding="utf-8")
        return result_path

    def _write_failed_result(self, run_dir: Path, exc: Exception) -> None:
        """失败 run 在自己的 run 目录标记 status=failed（尽力而为，不遮蔽原错误）。

        旧 run 永不被触碰；run 未产出任何账本时 artifact_index 为空。
        """
        try:
            artifact_index = {}
            for name, filename in (
                ("plan", "plan.json"),
                ("execution_assets", "execution-assets.json"),
                ("timeline", "timeline.json"),
            ):
                candidate = Path(run_dir) / filename
                if candidate.is_file():
                    artifact_index[name] = str(candidate)
            failed = FinalResultManifest(
                run_id=self.run_id,
                status="failed",
                output_mp4="",
                warnings=self._warnings + [f"Run failed: {type(exc).__name__}: {exc}"],
                artifact_index=artifact_index,
            )
            (Path(run_dir) / "result.json").write_text(
                failed.model_dump_json(indent=2), encoding="utf-8",
            )
        except Exception:
            pass

    def _validate_plan_layouts(self, plan: PlanManifest) -> None:
        """布局裁判：一次收集全部 scene 的全部 LayoutIssue 再 fail fast。"""
        from md2video.config import MANIM_HEIGHT, MANIM_WIDTH
        from md2video.layout.resolve import resolve_scene_layout

        problems: list[str] = []
        for scene in plan.scenes:
            try:
                resolve_scene_layout(
                    scene.layout_type,
                    scene.layout_params,
                    scene.layout_regions,
                    MANIM_WIDTH,
                    MANIM_HEIGHT,
                    registry=self.layout_registry,
                )
            except ValueError as exc:
                problems.append(f"Invalid layout for scene {scene.id}: {exc}")
        if problems:
            raise ValueError(" | ".join(problems))

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

            # run 目录制：per-shot visual 是本次 run 的产物，落进 run 目录
            base_visual_dir = self.run_dir if self.run_dir is not None else self.artifacts_dir
            output_dir = base_visual_dir / "visuals" / scene_plan.id
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
            duration=float(visual_data.get("duration", 0.0) or 0.0),
        )
        execution_assets.visual_assets = [
            existing for existing in execution_assets.visual_assets
            if existing.shot_id != shot_plan_id
        ]
        execution_assets.visual_assets.append(asset)

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
