"""Tests for md2video.core.planner.rule_planner (Phase 2A)."""
from __future__ import annotations

from md2video.core.planner.rule_planner import RulePlanner, denormalize_scenes_to_segments
from md2video.manifest.schema import SegmentPlan, ShotPlan


def _seg(id, text, stype="content", **kw):
    return SegmentPlan(id=id, text=text, segment_type=stype, **kw)


class TestRulePlanner:
    def test_basic_grouping(self):
        segments = [
            _seg("s1", "大标题", "title_main"),
            _seg("s2", "副标题", "title_sub"),
            _seg("s3", "小重山", "section_header", section_context="小重山"),
            _seg("s4", "测试内容。", "content", section_context="小重山"),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 2
        # scene_001: title scene
        assert scenes[0].shots[0].segment_ids == ["s1", "s2"]
        # scene_002: content scene
        assert scenes[1].shots[0].segment_ids == ["s3", "s4"]
        assert scenes[1].section_context == "小重山"

    def test_markers_excluded(self):
        segments = [
            _seg("s1", "内容", "content", section_context="S1"),
            _seg("s2", "[music_start bgm]", "marker_music",
                 marker_data={"kind": "start", "name": "bgm"}),
            _seg("s3", "更多", "content", section_context="S1"),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 3
        # marker is singleton
        assert scenes[1].shots[0].segment_ids == ["s2"]
        # content scenes on both sides
        assert scenes[0].shots[0].segment_ids == ["s1"]
        assert scenes[2].shots[0].segment_ids == ["s3"]

    def test_section_boundary(self):
        segments = [
            _seg("s1", "第一节", "section_header", section_context="第一节"),
            _seg("s2", "内容A。", "content", section_context="第一节"),
            _seg("s3", "第二节", "section_header", section_context="第二节"),
            _seg("s4", "内容B。", "content", section_context="第二节"),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 2
        assert scenes[0].section_context == "第一节"
        assert scenes[1].section_context == "第二节"

    def test_max_length_split(self):
        """Content exceeding MAX_SCENE_CHARS is split into multiple scenes."""
        # ~55 chars each, 4 * 55 = 220 > MAX_SCENE_CHARS(200)
        long_text = "这是一个非常长的测试句子用来验证场景分组拆分功能当累计字符数超过两百的时候应该自动拆分成多个不同的场景"
        segments = [
            _seg("s1", "节", "section_header", section_context="节"),
            _seg("s2", long_text, "content", section_context="节"),
            _seg("s3", long_text, "content", section_context="节"),
            _seg("s4", long_text, "content", section_context="节"),
            _seg("s5", long_text, "content", section_context="节"),
        ]
        scenes = RulePlanner().plan(segments)
        # Should be split into multiple scenes (200 char limit)
        assert len(scenes) >= 2
        # All segments should be covered
        all_ids = [sid for sc in scenes for shot in sc.shots for sid in shot.segment_ids]
        assert all_ids == ["s1", "s2", "s3", "s4", "s5"]

    def test_explicit_segment_breaks_scene(self):
        segments = [
            _seg("s1", "内容A", "content", section_context="S1"),
            _seg("s2", "特殊", "content", explicit=True,
                 visual_type="stock_image", visual_params={"query": "test"}),
            _seg("s3", "内容B", "content", section_context="S1"),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 3
        assert scenes[1].visual_type == "stock_image"
        assert scenes[1].visual_params == {"query": "test"}
        assert scenes[1].shots[0].segment_ids == ["s2"]

    def test_explicit_not_overridden(self):
        segments = [
            _seg("s1", "特殊", "content", explicit=True,
                 visual_type="custom", visual_params={"key": "val"}),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 1
        assert scenes[0].visual_type == "custom"

    def test_empty_input(self):
        assert RulePlanner().plan([]) == []

    def test_all_markers(self):
        segments = [
            _seg("s1", "[music_start bgm]", "marker_music",
                 marker_data={"kind": "start", "name": "bgm"}),
            _seg("s2", "[music_end bgm]", "marker_music",
                 marker_data={"kind": "end", "name": "bgm"}),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 2
        assert all(len(sc.shots) == 1 for sc in scenes)
        assert all(len(sc.shots[0].segment_ids) == 1 for sc in scenes)

    def test_section_context_preserved(self):
        segments = [
            _seg("s1", "标题", "section_header", section_context="第一章"),
            _seg("s2", "内容。", "content", section_context="第一章"),
        ]
        scenes = RulePlanner().plan(segments)
        assert scenes[0].section_context == "第一章"

    def test_image_marker_singleton(self):
        segments = [
            _seg("s1", "内容", "content", section_context="S1"),
            _seg("s2", "[image_start logo]", "marker_image",
                 marker_data={"kind": "start", "name": "logo"}),
            _seg("s3", "更多", "content", section_context="S1"),
            _seg("s4", "[image_end logo]", "marker_image",
                 marker_data={"kind": "end", "name": "logo"}),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 4
        # image markers are singletons
        assert scenes[1].shots[0].segment_ids == ["s2"]
        assert scenes[3].shots[0].segment_ids == ["s4"]

    def test_all_segments_covered(self):
        """Every segment appears in exactly one scene."""
        segments = [
            _seg("s1", "大标题", "title_main"),
            _seg("s2", "副标题", "title_sub"),
            _seg("s3", "节", "section_header", section_context="S"),
            _seg("s4", "内容。", "content", section_context="S"),
            _seg("s5", "[music_start bgm]", "marker_music",
                 marker_data={"kind": "start", "name": "bgm"}),
            _seg("s6", "更多。", "content", section_context="S"),
        ]
        scenes = RulePlanner().plan(segments)
        all_ids = [sid for sc in scenes for shot in sc.shots for sid in shot.segment_ids]
        assert len(all_ids) == len(segments)
        assert set(all_ids) == {s.id for s in segments}
        # No duplicates
        assert len(all_ids) == len(set(all_ids))

    def test_backward_compat_all_text_only(self):
        """Typical input produces all text_only scenes."""
        segments = [
            _seg("s1", "大标题", "title_main"),
            _seg("s2", "副标题", "title_sub"),
            _seg("s3", "节标题", "section_header", section_context="节"),
            _seg("s4", "内容。", "content", section_context="节"),
        ]
        scenes = RulePlanner().plan(segments)
        assert all(sc.visual_type == "text_only" for sc in scenes)
        assert all(sc.visual_params == {} for sc in scenes)

    def test_section_header_alone(self):
        """Section header with no content forms its own scene."""
        segments = [
            _seg("s1", "节A", "section_header", section_context="节A"),
            _seg("s2", "节B", "section_header", section_context="节B"),
        ]
        scenes = RulePlanner().plan(segments)
        assert len(scenes) == 2
        assert scenes[0].shots[0].segment_ids == ["s1"]
        assert scenes[1].shots[0].segment_ids == ["s2"]

    def test_appendix_segment(self):
        """Appendix segments after content are grouped in the same scene
        unless separated by a section_header."""
        segments = [
            _seg("s1", "节", "section_header", section_context="正文"),
            _seg("s2", "正文。", "content", section_context="正文"),
            _seg("s3", "附录内容。", "appendix", section_context=""),
        ]
        scenes = RulePlanner().plan(segments)
        # appendix continues in same scene (no section_header boundary)
        assert len(scenes) == 1
        assert scenes[0].shots[0].segment_ids == ["s1", "s2", "s3"]

    def test_scene_ids_sequential(self):
        segments = [
            _seg("s1", "标题", "title_main"),
            _seg("s2", "节", "section_header", section_context="S"),
            _seg("s3", "内容。", "content", section_context="S"),
        ]
        scenes = RulePlanner().plan(segments)
        ids = [sc.id for sc in scenes]
        assert ids == ["scene_001", "scene_002"]

    def test_shot_ids_sequential(self):
        """Shot IDs are globally sequential across scenes."""
        segments = [
            _seg("s1", "标题", "title_main"),
            _seg("s2", "副标题", "title_sub"),
            _seg("s3", "节", "section_header", section_context="S"),
            _seg("s4", "内容。", "content", section_context="S"),
        ]
        scenes = RulePlanner().plan(segments)
        shot_ids = [shot.id for sc in scenes for shot in sc.shots]
        assert shot_ids == ["shot_001", "shot_002"]


class TestDenormalize:
    def test_copies_visual_to_segments(self):
        from md2video.manifest.schema import ScenePlan
        segments = [_seg("s1", "内容"), _seg("s2", "更多")]
        scenes = [ScenePlan(
            id="scene_001",
            visual_type="stock_image",
            visual_params={"query": "test"},
            shots=[ShotPlan(id="shot_001", segment_ids=["s1", "s2"])],
        )]
        denormalize_scenes_to_segments(segments, scenes)
        assert segments[0].visual_type == "stock_image"
        assert segments[0].visual_params == {"query": "test"}
        assert segments[1].visual_type == "stock_image"

    def test_explicit_not_overridden(self):
        from md2video.manifest.schema import ScenePlan
        explicit = _seg("s1", "特殊", explicit=True,
                        visual_type="custom", visual_params={"k": "v"})
        segments = [explicit]
        scenes = [ScenePlan(
            id="scene_001",
            visual_type="text_only",
            shots=[ShotPlan(id="shot_001", segment_ids=["s1"])],
        )]
        denormalize_scenes_to_segments(segments, scenes)
        assert segments[0].visual_type == "custom"
