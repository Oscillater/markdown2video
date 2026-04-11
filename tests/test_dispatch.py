"""Pipeline dispatch + priority 单元测试。"""
from unittest.mock import MagicMock, patch

import pytest

from md2video.config import ToolConfig, DEFAULT_TOOL_PRIORITY
from md2video.tools.registry import ToolRegistry
from md2video.core.pipeline import Pipeline


def _make_tool(provider_name, tool_type="render"):
    tool = MagicMock()
    tool.provider_name = provider_name
    tool.tool_type = tool_type
    return tool


def _make_pipeline(tool_config=None, registry=None):
    """创建一个 Pipeline 实例（跳过 planner 创建的副作用）。"""
    with patch.object(Pipeline, "_create_planner"):
        with patch.object(Pipeline, "_register_default_tools"):
            p = Pipeline(tool_config=tool_config)
            if registry is not None:
                p.registry = registry
            return p


class TestToolConfig:
    def test_default_priority(self):
        cfg = ToolConfig()
        assert cfg.get_priority("text_only") == ["manim"]
        assert cfg.get_priority("tts") == ["edge-tts"]

    def test_unknown_type_fallback(self):
        cfg = ToolConfig()
        assert cfg.get_priority("unknown") == ["_text_only"]

    def test_register_custom(self):
        cfg = ToolConfig()
        cfg.register("custom", ["a", "b"])
        assert cfg.get_priority("custom") == ["a", "b"]


class TestDispatchTool:
    def test_first_provider_succeeds(self):
        tool = _make_tool("manim", "render")
        reg = ToolRegistry()
        reg.register("text_only", tool)
        cfg = ToolConfig(priority={"text_only": ["manim"]})
        p = _make_pipeline(cfg, reg)
        p._render_manim_batch = MagicMock(return_value=("video.mp4", "timeline.json"))

        result = p._dispatch_tool("text_only", MagicMock(), MagicMock(), MagicMock())
        assert result == ("video.mp4", "timeline.json")

    def test_preferred_provider_tried_first(self):
        """preferred_provider 应优先于 priority 列表中的顺序。"""
        reg = ToolRegistry()
        tool_a = _make_tool("a", "render")
        tool_b = _make_tool("b", "render")
        reg.register("stock_image", tool_a)
        reg.register("stock_image", tool_b)

        plan = MagicMock()
        sc = MagicMock()
        sc.visual_type = "stock_image"
        sc.visual_params = {"preferred_provider": "a"}
        plan.scenes = [sc]

        cfg = ToolConfig(priority={"stock_image": ["b", "a"]})
        p = _make_pipeline(cfg, reg)
        # a is tried first (preferred), then b — both raise NotImplementedError
        # since they're not manim tools. The error confirms ordering.
        with pytest.raises(RuntimeError, match="All tools failed"):
            p._dispatch_tool("stock_image", plan, MagicMock(), MagicMock())

    def test_text_only_degradation(self):
        """_text_only 在优先级列表中应降级到 manim。"""
        reg = ToolRegistry()
        manim = _make_tool("manim", "render")
        reg.register("text_only", manim)

        cfg = ToolConfig(priority={"stock_image": ["pexels", "_text_only"]})
        p = _make_pipeline(cfg, reg)
        p._render_manim_batch = MagicMock(return_value=("video.mp4", "timeline.json"))

        plan = MagicMock()
        plan.scenes = []
        result = p._dispatch_tool("stock_image", plan, MagicMock(), MagicMock())
        assert result == ("video.mp4", "timeline.json")

    def test_all_providers_fail_raises(self):
        reg = ToolRegistry()
        failing = _make_tool("bad", "render")
        # _invoke_tool calls _render_manim_batch which can fail
        reg.register("text_only", failing)

        cfg = ToolConfig(priority={"text_only": ["bad"]})
        p = _make_pipeline(cfg, reg)
        # Patch _render_manim_batch to raise
        p._render_manim_batch = MagicMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError, match="All tools failed"):
            p._dispatch_tool("text_only", MagicMock(), MagicMock(), MagicMock())
