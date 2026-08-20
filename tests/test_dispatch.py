"""Pipeline dispatch + priority 单元测试。"""
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from PIL import Image

from md2video.config import ToolConfig, DEFAULT_TOOL_PRIORITY
from md2video.tools.registry import ToolRegistry
from md2video.core.pipeline import Pipeline
from md2video.manifest.schema import (
    PlanManifest, ResultManifest, SceneResult, ShotResult, VisualResult,
    SegmentResult, ScenePlan, ShotPlan,
)
from md2video.tools.image.local_image_tool import LocalImageTool


def _make_tool(provider_name, tool_type="image"):
    tool = MagicMock()
    tool.provider_name = provider_name
    tool.tool_type = tool_type
    tool.execute.return_value = {
        "visuals": [{"shot_id": "shot_001", "path": "/tmp/img.jpg", "width": 800, "height": 600, "source": "pexels"}],
    }
    return tool


def _make_pipeline(tool_config=None, registry=None):
    """创建一个 Pipeline 实例（跳过 planner 创建的副作用）。"""
    with patch.object(Pipeline, "_create_planner"):
        with patch.object(Pipeline, "_register_default_tools"):
            p = Pipeline(tool_config=tool_config)
            if registry is not None:
                p.registry = registry
            return p


def _make_scene_plan(scene_id="scene_001", visual_type="stock_image", shot_ids=None, **kw):
    """创建一个 ScenePlan 用于测试。"""
    shots = [ShotPlan(id=sid, segment_ids=[f"seg_{sid}"]) for sid in (shot_ids or ["shot_001"])]
    return ScenePlan(
        id=scene_id,
        visual_type=visual_type,
        visual_params=kw.get("visual_params", {}),
        layout_type=kw.get("layout_type", "center_title_body"),
        layout_params=kw.get("layout_params", {}),
        section_context=kw.get("section_context", "test"),
        shots=shots,
    )


def _make_result_with_scenes(scene_ids, shot_ids_per_scene):
    """创建一个包含 SceneResult/ShotResult 的 ResultManifest。"""
    result = ResultManifest()
    t = 0.0
    for scene_id, shot_ids in zip(scene_ids, shot_ids_per_scene):
        shot_results = []
        for sid in shot_ids:
            shot_results.append(ShotResult(id=sid, segment_ids=[f"seg_{sid}"], start=t, end=t + 2.0))
            t += 2.0
        result.scenes.append(SceneResult(id=scene_id, shots=shot_results, start=0.0, end=t))
    return result


class TestToolConfig:
    def test_default_priority(self):
        cfg = ToolConfig()
        assert "text_only" not in DEFAULT_TOOL_PRIORITY
        assert cfg.get_priority("text_only") == ["_text_only"]
        assert cfg.get_priority("tts") == ["edge-tts"]

    def test_unknown_type_fallback(self):
        cfg = ToolConfig()
        assert cfg.get_priority("unknown") == ["_text_only"]

    def test_register_custom(self):
        cfg = ToolConfig()
        cfg.register("custom", ["a", "b"])
        assert cfg.get_priority("custom") == ["a", "b"]


class TestDispatchVisualTool:
    def test_dispatch_visual_tool_success(self):
        """工具成功时填充 ShotResult.visual。"""
        tool = _make_tool("pexels")
        reg = ToolRegistry()
        reg.register("stock_image", tool)

        cfg = ToolConfig(priority={"stock_image": ["pexels"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(visual_type="stock_image")
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        p._dispatch_visual_tool(scene, plan, result)

        # 验证 tool.execute 被调用
        assert tool.execute.called
        # 验证 ShotResult.visual 被填充
        assert result.scenes[0].shots[0].visual.path == "/tmp/img.jpg"
        assert result.scenes[0].shots[0].visual.source == "pexels"
        assert result.scenes[0].shots[0].visual.width == 800

    def test_preferred_provider_first(self):
        """preferred_provider 优先于 priority 列表中的顺序。"""
        tool_preferred = _make_tool("a")
        tool_fallback = _make_tool("b")
        reg = ToolRegistry()
        reg.register("stock_image", tool_preferred)
        reg.register("stock_image", tool_fallback)

        cfg = ToolConfig(priority={"stock_image": ["b", "a"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(visual_type="stock_image", visual_params={"preferred_provider": "a"})
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        p._dispatch_visual_tool(scene, plan, result)

        # 优先调用 preferred provider "a"
        assert tool_preferred.execute.called
        assert not tool_fallback.execute.called

    def test_all_providers_fail_warns(self):
        """全部 provider 失败时打印 warning，不抛异常。"""
        failing = _make_tool("bad")
        failing.execute.side_effect = RuntimeError("API error")
        reg = ToolRegistry()
        reg.register("stock_image", failing)

        cfg = ToolConfig(priority={"stock_image": ["bad"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(visual_type="stock_image")
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        # 不应抛异常
        p._dispatch_visual_tool(scene, plan, result)
        # visual 应保持默认空值
        assert result.scenes[0].shots[0].visual.path == ""

    def test_no_tool_available_warns(self):
        """没有任何已注册的工具时打印 warning。"""
        reg = ToolRegistry()  # 空 registry
        cfg = ToolConfig(priority={"stock_image": ["pexels", "pixabay"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(visual_type="stock_image")
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        # 不应抛异常
        p._dispatch_visual_tool(scene, plan, result)

    def test_invoke_visual_tool_input(self):
        """验证传递给 tool.execute() 的 input_data 结构正确。"""
        tool = _make_tool("pexels")
        reg = ToolRegistry()
        reg.register("stock_image", tool)

        cfg = ToolConfig(priority={"stock_image": ["pexels"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(
            visual_type="stock_image",
            visual_params={"query": "AI neural network"},
            layout_type="image_top_text_bottom",
            layout_params={"split": "text_focus"},
        )
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        p._dispatch_visual_tool(scene, plan, result)

        call_args = tool.execute.call_args
        input_data = call_args[0][0]
        assert "scene" in input_data
        assert input_data["scene"]["visual_type"] == "stock_image"
        assert input_data["scene"]["visual_params"] == {"query": "AI neural network"}
        assert input_data["scene"]["layout_type"] == "image_top_text_bottom"
        assert input_data["scene"]["layout_params"] == {"split": "text_focus"}
        assert "shot" in input_data
        assert input_data["shot"]["id"] == "shot_001"
        assert "segments" in input_data
        assert "output_dir" in input_data

    def test_apply_visual_result(self):
        """直接测试 _apply_visual_result helper。"""
        p = _make_pipeline()
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        tool_output = {
            "visuals": [{"shot_id": "shot_001", "path": "/img.jpg", "width": 1024, "height": 768, "source": "pixabay"}],
        }
        p._apply_visual_result(tool_output, "shot_001", result)
        assert result.scenes[0].shots[0].visual.path == "/img.jpg"
        assert result.scenes[0].shots[0].visual.source == "pixabay"
        assert result.scenes[0].shots[0].visual.width == 1024

    def test_apply_visual_result_fallback_first(self):
        """输出中没有匹配的 shot_id 时，取第一个 visual。"""
        p = _make_pipeline()
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        tool_output = {
            "visuals": [{"shot_id": "other_shot", "path": "/img.jpg", "width": 800, "height": 600, "source": "pexels"}],
        }
        p._apply_visual_result(tool_output, "shot_001", result)
        # fallback 到第一个 visual
        assert result.scenes[0].shots[0].visual.path == "/img.jpg"

    def test_local_image_dispatch(self, tmp_path):
        """local provider 可以写入 ShotResult.visual。"""
        image_path = tmp_path / "local_image.jpg"
        Image.new("RGB", (500, 631), color=(32, 96, 160)).save(image_path)
        plan = PlanManifest(
            segments=[],
            scenes=[
                _make_scene_plan(
                    visual_type="stock_image",
                    visual_params={"preferred_provider": "local", "path": image_path.name},
                ),
            ],
        )
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        reg = ToolRegistry()
        reg.register("stock_image", LocalImageTool())
        cfg = ToolConfig(priority={"stock_image": ["local"]})
        p = _make_pipeline(cfg, reg)

        p._dispatch_visual_tool(plan.scenes[0], plan, result, base_dir=tmp_path)

        visual = result.scenes[0].shots[0].visual
        assert visual.path == str(image_path.resolve())
        assert visual.source == "local"
        assert visual.width == 500
        assert visual.height == 631

    def test_explicit_local_image_failure_is_hard_fail(self):
        reg = ToolRegistry()
        reg.register("stock_image", LocalImageTool())
        cfg = ToolConfig(priority={"stock_image": ["local"]})
        p = _make_pipeline(cfg, reg)

        scene = _make_scene_plan(
            visual_type="stock_image",
            visual_params={"preferred_provider": "local", "path": "missing.jpg"},
        )
        plan = PlanManifest(segments=[], scenes=[scene])
        result = _make_result_with_scenes(["scene_001"], [["shot_001"]])

        with pytest.raises(FileNotFoundError, match="Local image not found"):
            p._dispatch_visual_tool(
                scene,
                plan,
                result,
                base_dir=Path(__file__).parent / "test_data",
            )


class TestDispatchRender:
    def test_execute_plan_validates_layout_before_tts(self, tmp_path):
        p = _make_pipeline()
        p._prepare_execution_assets = MagicMock()
        plan = PlanManifest(
            segments=[],
            scenes=[
                _make_scene_plan(
                    scene_id="scene_bad",
                    layout_type="missing_layout",
                ),
            ],
        )

        with pytest.raises(ValueError, match="Invalid layout for scene scene_bad"):
            p._execute_plan(plan, tmp_path / "out.mp4", tmp_path, tmp_path)

        assert not p._prepare_execution_assets.called

    def test_dispatch_visual_tools_validates_layout_before_tools(self, tmp_path):
        p = _make_pipeline()
        p._dispatch_visual_tool = MagicMock()
        plan = PlanManifest(
            segments=[],
            scenes=[
                _make_scene_plan(
                    scene_id="scene_bad",
                    visual_type="stock_image",
                    layout_type="missing_layout",
                ),
            ],
        )
        result = ResultManifest()

        with pytest.raises(ValueError, match="Invalid layout for scene scene_bad"):
            p._dispatch_visual_tools(plan, result, tmp_path)

        assert not p._dispatch_visual_tool.called

    def test_execute_plan_rejects_manim_visual_type_before_tts(self, tmp_path):
        p = _make_pipeline()
        p._prepare_execution_assets = MagicMock()
        plan = PlanManifest(
            segments=[],
            scenes=[
                _make_scene_plan(
                    scene_id="scene_manim",
                    visual_type="manim",
                ),
            ],
        )

        with pytest.raises(ValueError, match="Unsupported visual_type.*scene_manim.*manim"):
            p._execute_plan(plan, tmp_path / "out.mp4", tmp_path, tmp_path)

        assert not p._prepare_execution_assets.called

    def test_dispatch_visual_tools_rejects_manim_visual_type(self, tmp_path):
        p = _make_pipeline()
        p._dispatch_visual_tool = MagicMock()
        plan = PlanManifest(
            segments=[],
            scenes=[
                _make_scene_plan(
                    scene_id="scene_manim",
                    visual_type="manim",
                ),
            ],
        )
        result = ResultManifest()

        with pytest.raises(ValueError, match="Unsupported visual_type.*scene_manim.*manim"):
            p._dispatch_visual_tools(plan, result, tmp_path)

        assert not p._dispatch_visual_tool.called

    def test_dispatch_visual_tools_text_only_only(self):
        """全部 text_only 时不调用 visual tool。"""
        p = _make_pipeline()
        p._dispatch_visual_tool = MagicMock()

        plan = PlanManifest(segments=[], scenes=[
            _make_scene_plan(scene_id="s1", visual_type="text_only"),
        ])
        result = ResultManifest()

        p._dispatch_visual_tools(plan, result, Path.cwd())
        assert not p._dispatch_visual_tool.called

    def test_dispatch_visual_tools_mixed(self):
        """混合 text_only 和 stock_image 时，对 stock_image scene 调用 visual tool。"""
        p = _make_pipeline()
        p._dispatch_visual_tool = MagicMock()

        plan = PlanManifest(segments=[], scenes=[
            _make_scene_plan(scene_id="s1", visual_type="text_only"),
            _make_scene_plan(scene_id="s2", visual_type="stock_image"),
        ])
        result = ResultManifest()

        p._dispatch_visual_tools(plan, result, Path.cwd())
        # 只对 stock_image scene 调用 visual tool
        assert p._dispatch_visual_tool.call_count == 1
        assert p._dispatch_visual_tool.call_args[0][0].visual_type == "stock_image"

    def test_dispatch_render_is_deprecated(self):
        p = _make_pipeline()
        with pytest.raises(RuntimeError, match="_dispatch_render no longer renders"):
            p._dispatch_render()
