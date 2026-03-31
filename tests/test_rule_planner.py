"""Tests for md2video.core.planner.rule_planner."""
from __future__ import annotations

from md2video.core.planner.rule_planner import RulePlanner
from md2video.manifest.schema import SegmentPlan


class TestRulePlanner:
    def test_sets_text_only_for_non_explicit(self):
        segments = [
            SegmentPlan(id="s1", text="a", segment_type="content", visual_type="custom"),
            SegmentPlan(id="s2", text="b", segment_type="content", visual_type="other"),
        ]
        result = RulePlanner().plan(segments)
        assert result[0].visual_type == "text_only"
        assert result[0].visual_params == {}
        assert result[1].visual_type == "text_only"

    def test_preserves_explicit_segments(self):
        seg_explicit = SegmentPlan(
            id="s1", text="a", segment_type="content",
            explicit=True, visual_type="custom", visual_params={"key": "val"},
        )
        segments = [seg_explicit]
        RulePlanner().plan(segments)
        assert seg_explicit.visual_type == "custom"
        assert seg_explicit.visual_params == {"key": "val"}

    def test_returns_same_list(self):
        segments = [SegmentPlan(id="s1", text="a", segment_type="content")]
        result = RulePlanner().plan(segments)
        assert result is segments

    def test_empty_list(self):
        assert RulePlanner().plan([]) == []

    def test_mixed_explicit_and_non_explicit(self):
        segments = [
            SegmentPlan(id="s1", text="a", segment_type="content", explicit=False),
            SegmentPlan(id="s2", text="b", segment_type="content", explicit=True,
                        visual_type="special"),
            SegmentPlan(id="s3", text="c", segment_type="content", explicit=False),
        ]
        RulePlanner().plan(segments)
        assert segments[0].visual_type == "text_only"
        assert segments[1].visual_type == "special"
        assert segments[2].visual_type == "text_only"
