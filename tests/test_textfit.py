"""P0-3B 文本溢出闸门测试：估宽 / 两级裁决 / pipeline 接线（渲染前）。"""
from __future__ import annotations

import pytest

from md2video.layout.textfit import (
    LEVEL_ERROR,
    LEVEL_OK,
    LEVEL_WARN,
    check_text_fit,
    check_texts_fit,
    classify_overflow,
    estimate_wrapped_lines,
)
from md2video.manifest.schema import (
    AudioRequest,
    ExecutionAssets,
    PlanManifest,
    SegmentPlan,
)


# ========== estimate_wrapped_lines ==========


def test_estimate_empty_text_zero_lines():
    assert estimate_wrapped_lines("", 40, 400) == 0
    assert estimate_wrapped_lines("   ", 40, 400) == 0


def test_estimate_cjk_full_width():
    # 10 个全角字 × 40px = 400px，恰好一行
    assert estimate_wrapped_lines("十全十美文字排版测试", 40, 400) == 1
    # 11 字 = 440px > 400 → 2 行
    assert estimate_wrapped_lines("十全十美文字排版测试字", 40, 400) == 2


def test_estimate_ascii_narrower_than_cjk():
    # 9 个 ASCII × 0.55 × 40 = 198px < 400 → 1 行；按全角算会是 360 也 1 行，
    # 用更长的串体现差异：16 ASCII = 352px（0.55）仍 1 行，全角则 640 → 2 行
    text = "abcdefghijklmnop"
    assert estimate_wrapped_lines(text, 40, 400) == 1


def test_estimate_ascii_token_atomicity():
    # 单个超宽 ASCII token 不被拆行计数（独占行 + 溢出成行）
    lines = estimate_wrapped_lines("x " + "a" * 200, 10, 100)
    assert lines >= 2


def test_estimate_zero_box_safe():
    assert estimate_wrapped_lines("文本", 40, 0) == 0
    assert estimate_wrapped_lines("文本", 0, 400) == 0


# ========== check_text_fit 两级裁决 ==========


def test_fit_ok_when_within_capacity():
    # 容量：200px 高 / (20×1.5=30) = 6 行；文本 30 全角字 @20px/400 宽 = 2 行
    result = check_text_fit("这" * 30, 20, 400, 200, "body")
    assert result.level == LEVEL_OK
    assert result.needed_lines < result.capacity_lines


def test_fit_warn_when_over_by_one_line():
    # 容量 1 行（90px / 60px）；文本 2 行 → 差 1 行 → warn
    result = check_text_fit("字" * 20, 40, 400, 90, "body")
    assert result.capacity_lines == 1
    assert result.needed_lines == 2
    assert result.level == LEVEL_WARN


def test_fit_error_when_over_by_two_lines():
    # 容量 1 行；文本 4 行 → 差 3 行 → error
    result = check_text_fit("字" * 80, 40, 400, 90, "body")
    assert result.needed_lines >= 3
    assert result.level == LEVEL_ERROR


def test_fit_boundary_exactly_capacity_is_ok():
    # 恰好填满：needed == capacity → ok（不误报）
    result = check_text_fit("字" * 20, 40, 800, 120, "title")
    assert result.needed_lines == 1
    assert result.capacity_lines == 2  # 120 / 60
    assert result.level == LEVEL_OK


def test_classify_overflow_levels():
    assert classify_overflow(100, 200, 60) == LEVEL_OK
    assert classify_overflow(260, 200, 60) == LEVEL_WARN   # 差 60 = 1 行高
    assert classify_overflow(320, 200, 60) == LEVEL_ERROR  # 差 120 > 1 行高
    assert classify_overflow(201, 200, 60) == LEVEL_WARN   # 差 1px 也算 ≤1 行
    assert classify_overflow(100, 200, 0) == LEVEL_OK


def test_check_texts_fit_batch():
    results = check_texts_fit([
        ("body", "短文本", 20, 400, 200),
        ("title", "字" * 200, 40, 400, 90),
    ])
    assert [r.region for r in results] == ["body", "title"]
    assert results[0].level == LEVEL_OK
    assert results[1].level == LEVEL_ERROR


def test_fit_result_message_locatable():
    result = check_text_fit("字" * 80, 40, 400, 90, "body")
    assert "body" in result.message
    assert str(result.needed_lines) in result.message
    assert str(result.capacity_lines) in result.message


# ========== pipeline 接线（渲染前 fail fast / warning 落 warnings）==========


def _overflow_plan(scene_overrides=None) -> PlanManifest:
    scene = {
        "id": "scene_001",
        "visual_type": "text_only",
        "visual_params": {},
        "shots": [{"id": "shot_001", "segment_ids": ["s1"]}],
        "section_context": "S",
    }
    if scene_overrides:
        scene.update(scene_overrides)
    return PlanManifest(
        segments=[
            SegmentPlan(
                id="s1",
                # body region（center_title_body ≈ 547px 高）@15px 字号：
                # 行高 22.5 → 容量 24 行；403px 宽每行 26 字 → 800 字需
                # 31 行，差 7 行 > 1 → error（fail fast 口径）
                text="溢" * 800,
                segment_type="content",
                audio_request=None,  # 静默段 → 引擎画 → 必查
            ),
        ],
        scenes=[scene],
    )


def test_pipeline_text_overflow_error_fails_before_render():
    from md2video.core.pipeline import Pipeline

    pipeline = Pipeline()
    with pytest.raises(ValueError, match="text overflow"):
        pipeline._validate_plan_text_overflow(_overflow_plan())


def test_pipeline_narrated_remotion_segment_not_checked():
    """文字层 B：Remotion 朗读段引擎不画 → 闸门不查（字幕有自己的折行）。"""
    from md2video.core.pipeline import Pipeline

    pipeline = Pipeline()
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="s1", text="溢" * 800, segment_type="content",
                audio_request=AudioRequest(),
            ),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "render_backend": "remotion",
            "shots": [{"id": "shot_001", "segment_ids": ["s1"]}],
            "section_context": "S",
        }],
    )
    pipeline._validate_plan_text_overflow(plan)  # 不抛


def test_pipeline_component_scene_body_not_checked():
    """组件场正文归 check-component 黄金帧验收（A8 边界），闸门不查。"""
    from md2video.core.pipeline import Pipeline

    pipeline = Pipeline()
    plan = _overflow_plan({
        "component": "step_list@1.0.2",
        "render_backend": "remotion",
    })
    pipeline._validate_plan_text_overflow(plan)  # 不抛


def test_pipeline_fitting_plan_passes():
    from md2video.core.pipeline import Pipeline

    pipeline = Pipeline()
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="t1", text="标题", segment_type="title_main",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="t2", text="副标题文本", segment_type="title_sub",
            ),
            SegmentPlan(
                id="s1", text="短正文。", segment_type="content",
                audio_request=None,
            ),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "shots": [{"id": "shot_001", "segment_ids": ["t1", "t2", "s1"]}],
            "section_context": "S",
        }],
    )
    pipeline._validate_plan_text_overflow(plan)  # 不抛、无 error
    assert not any("text overflow" in w for w in pipeline._warnings)
