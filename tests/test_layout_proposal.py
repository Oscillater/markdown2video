"""A5 layout 直接提案：ScenePlan.layout_regions 入口 + 子构图 region 化。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from md2video.layout.resolve import (
    PROPOSAL_TEMPLATE_ID,
    evaluate_layout_proposal,
    resolve_scene_layout,
)
from md2video.layout.constraints import LayoutValidationError
from md2video.layout.registry import create_default_layout_registry
from md2video.manifest.schema import PlanManifest, ScenePlan, SegmentPlan, ShotPlan
from md2video.tools.render.manim_renderer_inputs import (
    ShotRenderUnit,
    compute_shot_layout,
    iter_shot_render_units,
    shot_layout_context,
)

# 与 center_title_body（density=normal）等价的提案
CTB_PROPOSAL = {
    "title": {"x": 0.08, "y": 0.06, "width": 0.84, "height": 0.20},
    "body": {"x": 0.08, "y": 0.30, "width": 0.84, "height": 0.64},
}


class TestEvaluateLayoutProposal:
    def test_valid_proposal_passes_same_validation_as_templates(self):
        layout, issues = evaluate_layout_proposal(CTB_PROPOSAL, 480, 854)
        assert issues == []
        assert layout.template_id == PROPOSAL_TEMPLATE_ID
        registry_layout = create_default_layout_registry().compute(
            "center_title_body", {}, 480, 854,
        )
        # 提案与模板产出同一套属性校验；等价 region 集合得到相同几何
        for name in ("title", "body"):
            proposed = layout.regions[name]
            templated = registry_layout.regions[name]
            assert proposed.x == pytest.approx(templated.x)
            assert proposed.y == pytest.approx(templated.y)
            assert proposed.width == pytest.approx(templated.width)
            assert proposed.height == pytest.approx(templated.height)

    def test_image_slot_may_bleed_and_sit_under_text(self):
        proposal = {
            "image": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "caption": {"x": 0.08, "y": 0.72, "width": 0.84, "height": 0.14},
        }
        layout, issues = evaluate_layout_proposal(proposal, 480, 854)
        assert issues == []
        # 视觉槽位豁免安全区/重叠检查，但 caption 仍是内容 region
        assert layout.content_region_names == ["caption"]

    def test_invalid_proposal_reports_all_issues(self):
        proposal = {
            "a": {"x": 0.0, "y": 0.0, "width": 0.30, "height": 0.04},  # 出安全区+太小
            "b": {"x": 0.10, "y": 0.02, "width": 0.60, "height": 0.30},  # 与 a 重叠
        }
        layout, issues = evaluate_layout_proposal(proposal, 480, 854)
        assert layout is None
        codes = {issue.code for issue in issues}
        assert {"outside_safe_area", "regions_overlap", "region_too_small"} <= codes

    def test_invalid_box_values_become_structured_issues(self):
        proposal = {
            "bad": {"x": 0.9, "y": 0.9, "width": 0.5, "height": 0.5},
        }
        layout, issues = evaluate_layout_proposal(proposal, 480, 854)
        assert layout is None
        assert [issue.code for issue in issues] == ["invalid_box"]
        assert issues[0].region == "bad"

    def test_resolve_raises_single_error_with_all_issues(self):
        with pytest.raises(LayoutValidationError) as exc_info:
            resolve_scene_layout("ignored", {}, {
                "a": {"x": 0.0, "y": 0.0, "width": 0.30, "height": 0.04},
                "b": {"x": 0.10, "y": 0.02, "width": 0.60, "height": 0.30},
            }, 480, 854)
        assert len(exc_info.value.issues) >= 3
        message = str(exc_info.value)
        assert "outside_safe_area" in message
        assert "regions_overlap" in message
        assert "region_too_small" in message

    def test_proposal_takes_precedence_over_layout_type(self):
        layout = resolve_scene_layout(
            "no_such_template", {}, CTB_PROPOSAL, 480, 854,
        )
        assert layout.template_id == PROPOSAL_TEMPLATE_ID


class TestScenePlanProposal:
    def test_scene_plan_accepts_layout_regions(self):
        scene = ScenePlan(id="s", layout_regions=CTB_PROPOSAL, shots=[])
        assert scene.layout_regions == CTB_PROPOSAL

    def test_iter_shot_render_units_carries_layout_regions(self):
        plan = PlanManifest(
            segments=[SegmentPlan(id="seg_001", text="x", segment_type="content")],
            scenes=[ScenePlan(
                id="scene_001", layout_regions=CTB_PROPOSAL,
                shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])],
            )],
        )
        units = list(iter_shot_render_units(plan))
        assert units[0].layout_regions == CTB_PROPOSAL

    def test_compute_shot_layout_resolves_proposal(self):
        unit = ShotRenderUnit(
            scene_id="scene_001", shot_id="shot_001",
            segments=(), cues=(),
            layout_type="center_title_body", layout_params={},
            layout_regions=CTB_PROPOSAL,
        )
        layout = compute_shot_layout(unit, 480, 854)
        assert layout.template_id == PROPOSAL_TEMPLATE_ID
        assert layout.regions["body"].height == pytest.approx(0.64)

    def test_shot_layout_context_without_proposal_uses_template(self):
        unit = ShotRenderUnit(
            scene_id="scene_001", shot_id="shot_001",
            segments=(), cues=(),
            layout_type="center_title_body", layout_params={},
        )
        ctx = shot_layout_context(unit, 4.5, 8.0)
        assert ctx.body is not None


class TestPipelineProposalGate:
    def _pipeline(self, tmp_path):
        from md2video.config import ToolConfig
        from md2video.core.pipeline import Pipeline

        with patch.object(Pipeline, "_create_planner"), \
                patch.object(Pipeline, "_register_default_tools"):
            pipeline = Pipeline(
                artifacts_dir=tmp_path,
                tool_config=ToolConfig(priority={"stock_image": ["local"]}),
            )
        return pipeline

    def test_invalid_proposal_fails_fast_before_tts(self, tmp_path):
        pipeline = self._pipeline(tmp_path)
        pipeline._prepare_execution_assets = MagicMock()
        bad_proposal = {
            "a": {"x": 0.0, "y": 0.0, "width": 0.30, "height": 0.04},
            "b": {"x": 0.10, "y": 0.02, "width": 0.60, "height": 0.30},
        }
        plan = PlanManifest(segments=[], scenes=[
            ScenePlan(id="scene_bad", layout_regions=bad_proposal, shots=[]),
        ])

        with pytest.raises(ValueError, match="Invalid layout for scene scene_bad"):
            pipeline._validate_plan_layouts(plan)
        assert not pipeline._prepare_execution_assets.called

    def test_all_scene_issues_reported_in_one_error(self, tmp_path):
        pipeline = self._pipeline(tmp_path)
        bad_proposal = {
            "a": {"x": 0.0, "y": 0.0, "width": 0.30, "height": 0.04},
            "b": {"x": 0.10, "y": 0.02, "width": 0.60, "height": 0.30},
        }
        plan = PlanManifest(segments=[], scenes=[
            ScenePlan(id="scene_a", layout_regions=bad_proposal, shots=[]),
            ScenePlan(id="scene_b", layout_regions=bad_proposal, shots=[]),
        ])

        with pytest.raises(ValueError) as exc_info:
            pipeline._validate_plan_layouts(plan)
        message = str(exc_info.value)
        assert "Invalid layout for scene scene_a" in message
        assert "Invalid layout for scene scene_b" in message

    def test_valid_proposal_passes_pipeline_gate(self, tmp_path):
        pipeline = self._pipeline(tmp_path)
        plan = PlanManifest(segments=[], scenes=[
            ScenePlan(id="scene_ok", layout_regions=CTB_PROPOSAL, shots=[]),
        ])
        pipeline._validate_plan_layouts(plan)


class TestAssemblerConsumesProposal:
    def test_attach_image_layout_regions_uses_proposal(self):
        from md2video.assembler.ffmpeg_assembler import attach_image_layout_regions

        proposal = {
            "image": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "caption": {"x": 0.08, "y": 0.72, "width": 0.84, "height": 0.14},
        }
        entries = [{
            "name": "shot_001", "src": "x.png", "start": 0.0, "end": 1.0,
            "layout_type": "full_bleed_image_caption_bottom",
            "layout_params": {},
            "layout_regions": proposal,
        }]
        attach_image_layout_regions(entries, 480, 854)
        # 全屏 image region -> 整帧像素矩形（偶数尺寸）
        assert entries[0]["region_px"] == {"left": 0, "top": 0, "width": 480, "height": 854}

    def test_shot_visual_entries_carry_scene_layout_regions(self):
        from md2video.assembler.ffmpeg_assembler import (
            extract_shot_visual_entries_from_assets,
        )
        from md2video.manifest.schema import ExecutionAssets, VisualAsset

        plan = PlanManifest(scenes=[ScenePlan(
            id="scene_001", layout_regions=CTB_PROPOSAL,
            shots=[ShotPlan(id="shot_001", segment_ids=[])],
        )])
        assets = ExecutionAssets(visual_assets=[
            VisualAsset(shot_id="shot_001", path="x.png", provider="local"),
        ])
        entries = extract_shot_visual_entries_from_assets(plan, assets)
        assert entries[0]["layout_regions"] == CTB_PROPOSAL


class TestSectionStackSubRegion:
    def test_center_title_body_defines_section_stack_equal_to_body(self):
        layout = create_default_layout_registry().compute(
            "center_title_body", {}, 480, 854,
        )
        assert layout.regions["section_stack"] == layout.regions["body"]
        # 嵌套子 region 不参加内容区重叠/安全区名单
        assert "section_stack" not in layout.content_region_names
        assert "section_stack" not in layout.safe_region_names

    def test_section_stack_falls_back_to_body_for_other_templates(self):
        for layout_type in ("image_top_text_bottom", "full_bleed_image_caption_bottom"):
            unit = ShotRenderUnit(
                scene_id="s", shot_id="sh", segments=(), cues=(),
                layout_type=layout_type, layout_params={},
            )
            ctx = shot_layout_context(unit, 4.5, 8.0)
            assert ctx.section_stack == ctx.body, layout_type

    def test_section_stack_placement_matches_body_values(self):
        unit = ShotRenderUnit(
            scene_id="s", shot_id="sh", segments=(), cues=(),
            layout_type="center_title_body", layout_params={},
        )
        ctx = shot_layout_context(unit, 4.5, 8.0)
        assert ctx.section_stack is not None
        # 渲染器堆叠边界消费的是 center/max_width/max_height 数值
        assert ctx.section_stack.center == ctx.body.center
        assert ctx.section_stack.max_width == ctx.body.max_width
        assert ctx.section_stack.max_height == ctx.body.max_height
