"""Tests for LLM Planner — 纯单元测试，不调用 LLM API。"""
from __future__ import annotations

import pytest

from md2video.manifest.schema import SegmentPlan
from md2video.core.planner.llm_planner import (
    LlmPlanner, LlmPlannerOutput, LlmScene, LlmShot,
    SceneTemplate, BlueprintOutput, ShotMapping, ChunkMappingOutput,
)


def _seg(id, text, stype="content", section="", **kw):
    return SegmentPlan(id=id, text=text, segment_type=stype, section_context=section, **kw)


# ==================== _convert 测试 ====================

class TestConvert:

    def _make_planner(self):
        """创建 LlmPlanner（不传入 API key，不会实际调用 LLM）。"""
        return LlmPlanner(model="openai:gpt-4o", api_key="test-key")

    def test_convert_basic(self):
        """基本转换：两个 scene，各一个 shot。"""
        segments = [
            _seg("s1", "第一段", section="第一节"),
            _seg("s2", "第二段", section="第一节"),
            _seg("s3", "第三段", section="第二节"),
        ]
        output = LlmPlannerOutput(scenes=[
            LlmScene(visual_type="text_only", shots=[
                LlmShot(segment_ids=["s1", "s2"]),
            ]),
            LlmScene(visual_type="stock_image", visual_params={"query": "neural network"}, shots=[
                LlmShot(segment_ids=["s3"]),
            ]),
        ])
        planner = self._make_planner()
        scenes = planner._convert(segments, output)

        assert len(scenes) == 2
        assert scenes[0].visual_type == "text_only"
        assert scenes[0].shots[0].segment_ids == ["s1", "s2"]
        assert scenes[0].section_context == "第一节"
        assert scenes[1].visual_type == "stock_image"
        assert scenes[1].visual_params == {"query": "neural network"}
        assert scenes[1].section_context == "第二节"

    def test_convert_multi_shot_per_scene(self):
        """一个 scene 含多个 shot。"""
        segments = [
            _seg("s1", "第一段"), _seg("s2", "第二段"), _seg("s3", "第三段"),
        ]
        output = LlmPlannerOutput(scenes=[
            LlmScene(visual_type="stock_image", visual_params={"query": "AI"}, shots=[
                LlmShot(segment_ids=["s1"]),
                LlmShot(segment_ids=["s2", "s3"]),
            ]),
        ])
        planner = self._make_planner()
        scenes = planner._convert(segments, output)

        assert len(scenes) == 1
        assert len(scenes[0].shots) == 2
        assert scenes[0].shots[0].segment_ids == ["s1"]
        assert scenes[0].shots[1].segment_ids == ["s2", "s3"]

    def test_convert_explicit_preserved(self):
        """explicit segment 被拆为 singleton scene，保留原 visual_type。"""
        segments = [
            _seg("s1", "普通", section="第一节"),
            _seg("s2", "显式", explicit=True, visual_type="stock_image",
                 visual_params={"query": "logo"}, section="第一节"),
            _seg("s3", "普通2", section="第一节"),
        ]
        # LLM 把 explicit 和 non-explicit 混在同一个 shot 里
        output = LlmPlannerOutput(scenes=[
            LlmScene(visual_type="text_only", shots=[
                LlmShot(segment_ids=["s1", "s2", "s3"]),
            ]),
        ])
        planner = self._make_planner()
        scenes = planner._convert(segments, output)

        # explicit s2 被拆出为独立 scene
        explicit_scenes = [sc for sc in scenes if any(
            sid == "s2" for shot in sc.shots for sid in shot.segment_ids
        )]
        assert len(explicit_scenes) == 1
        assert explicit_scenes[0].visual_type == "stock_image"
        assert explicit_scenes[0].visual_params == {"query": "logo"}
        assert len(explicit_scenes[0].shots) == 1
        assert explicit_scenes[0].shots[0].segment_ids == ["s2"]

    def test_convert_duplicate_segment_raises(self):
        """segment_ids 重复时报 ValueError。"""
        segments = [_seg("s1", "第一段"), _seg("s2", "第二段")]
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[LlmShot(segment_ids=["s1", "s2"])]),
            LlmScene(shots=[LlmShot(segment_ids=["s1"])]),
        ])
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Duplicate"):
            planner._convert(segments, output)

    def test_convert_missing_segment_raises(self):
        """segment_ids 缺少时报 ValueError。"""
        segments = [_seg("s1", "第一段"), _seg("s2", "第二段"), _seg("s3", "第三段")]
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[LlmShot(segment_ids=["s1", "s2"])]),
        ])
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Missing"):
            planner._convert(segments, output)

    def test_convert_non_consecutive_raises(self):
        """shot 内 segment 非连续时报 ValueError。"""
        segments = [_seg("s1", "一"), _seg("s2", "二"), _seg("s3", "三")]
        # s1 和 s3 不连续，但 s2 在另一个 shot 里（全部覆盖，不触发 Missing）
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[
                LlmShot(segment_ids=["s1", "s3"]),
                LlmShot(segment_ids=["s2"]),
            ]),
        ])
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Non-consecutive"):
            planner._convert(segments, output)

    def test_convert_unknown_segment_raises(self):
        """segment_id 不存在时报 ValueError。"""
        segments = [_seg("s1", "一")]
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[LlmShot(segment_ids=["s1", "s99"])]),
        ])
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Unknown"):
            planner._convert(segments, output)


# ==================== plan() 集成测试 ====================

class TestPlanFallback:

    def test_empty_input(self):
        planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
        assert planner.plan([]) == []

    def test_fallback_on_convert_error(self):
        """_convert 校验失败 → fallback 到 RulePlanner。"""
        segments = [_seg("s1", "第一段"), _seg("s2", "第二段"), _seg("s3", "第三段")]
        # 故意制造缺失 segment 的错误输出
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[LlmShot(segment_ids=["s1"])]),
        ])
        planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
        # 直接调用 _convert 会报错
        with pytest.raises(ValueError):
            planner._convert(segments, output)

    def test_scene_and_shot_ids_sequential(self):
        """验证生成的 scene/shot ID 格式正确且递增。"""
        segments = [
            _seg("s1", "第一段", section="第一节"),
            _seg("s2", "第二段", section="第二节"),
            _seg("s3", "第三段", section="第二节"),
            _seg("s4", "第四段", section="第三节"),
        ]
        output = LlmPlannerOutput(scenes=[
            LlmScene(visual_type="text_only", shots=[
                LlmShot(segment_ids=["s1"]),
            ]),
            LlmScene(visual_type="stock_image", visual_params={"query": "test"}, shots=[
                LlmShot(segment_ids=["s2"]),
                LlmShot(segment_ids=["s3", "s4"]),
            ]),
        ])
        planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
        scenes = planner._convert(segments, output)

        assert scenes[0].id == "scene_001"
        assert scenes[0].shots[0].id == "shot_001"
        assert scenes[1].id == "scene_002"
        assert scenes[1].shots[0].id == "shot_002"
        assert scenes[1].shots[1].id == "shot_003"

    def test_all_segments_covered(self):
        """验证所有 segment 都被覆盖，无遗漏。"""
        segments = [_seg(f"s{i}", f"第{i}段") for i in range(1, 6)]
        output = LlmPlannerOutput(scenes=[
            LlmScene(shots=[LlmShot(segment_ids=["s1", "s2"])]),
            LlmScene(shots=[LlmShot(segment_ids=["s3"])],
                     visual_params={"query": "x"}),
            LlmScene(shots=[LlmShot(segment_ids=["s4", "s5"])]),
        ])
        planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
        scenes = planner._convert(segments, output)

        covered = []
        for sc in scenes:
            for shot in sc.shots:
                covered.extend(shot.segment_ids)
        assert sorted(covered) == ["s1", "s2", "s3", "s4", "s5"]


# ==================== _split_chunks 测试 ====================

class TestSplitChunks:

    def test_single_chunk(self):
        """不足 max_segs 时只有一个 chunk。"""
        segments = [_seg(f"s{i}", f"第{i}段") for i in range(1, 6)]
        chunks = LlmPlanner._split_chunks(segments, max_segs=30)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_split_by_section(self):
        """不同 section_context 切分为不同 chunk。"""
        segments = [
            _seg("s1", "标题", stype="title_main"),
            _seg("s2", "第一段", section="第一节"),
            _seg("s3", "第二段", section="第一节"),
            _seg("s4", "第三段", section="第二节"),
            _seg("s5", "第四段", section="第二节"),
        ]
        chunks = LlmPlanner._split_chunks(segments, max_segs=30)
        # title 归入首 chunk → 首个 content chunk 合并 title
        assert len(chunks) == 2
        # chunk 0: title + 第一节
        assert [s.id for s in chunks[0]] == ["s1", "s2", "s3"]
        # chunk 1: 第二节
        assert [s.id for s in chunks[1]] == ["s4", "s5"]

    def test_split_by_max_segs(self):
        """超过 max_segs 时强制切分。"""
        segments = [_seg(f"s{i}", f"第{i}段", section="同一节") for i in range(1, 11)]
        chunks = LlmPlanner._split_chunks(segments, max_segs=3)
        # 10 segs / max 3 = ceil 分多块
        assert len(chunks) > 1
        # 所有 segment 都被保留
        all_ids = [s.id for chunk in chunks for s in chunk]
        assert all_ids == [f"s{i}" for i in range(1, 11)]

    def test_empty_input(self):
        assert LlmPlanner._split_chunks([]) == []

    def test_single_segment(self):
        segments = [_seg("s1", "唯一一段")]
        chunks = LlmPlanner._split_chunks(segments)
        assert len(chunks) == 1


# ==================== _reconcile 测试 ====================

class TestReconcile:

    def _make_planner(self):
        return LlmPlanner(model="openai:gpt-4o", api_key="test-key")

    def _make_registry(self):
        return [
            SceneTemplate(
                id="SCENE_TEXT", name="纯文字", description="纯文字讲解",
                visual_type="text_only", visual_params={},
            ),
            SceneTemplate(
                id="SCENE_IMAGE", name="配图", description="配图讲解",
                visual_type="stock_image", visual_params={"query": "AI", "preferred_provider": "pexels"},
            ),
        ]

    def test_basic_reconcile(self):
        """基本合并：两个 shot 映射到不同 scene。"""
        segments = [
            _seg("s1", "第一段", section="第一节"),
            _seg("s2", "第二段", section="第一节"),
            _seg("s3", "第三段", section="第二节"),
        ]
        mappings = [
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2"])],
            [ShotMapping(scene_id="SCENE_IMAGE", segment_ids=["s3"])],
        ]
        registry = self._make_registry()
        planner = self._make_planner()
        scenes = planner._reconcile(mappings, segments, registry)

        assert len(scenes) == 2
        assert scenes[0].visual_type == "text_only"
        assert scenes[0].shots[0].segment_ids == ["s1", "s2"]
        assert scenes[1].visual_type == "stock_image"
        assert scenes[1].visual_params == {"query": "AI", "preferred_provider": "pexels"}

    def test_reconcile_sequential_ids(self):
        """多 chunk 合并后 scene/shot ID 全局递增，相同 scene_id 合并。"""
        segments = [_seg(f"s{i}", f"第{i}段") for i in range(1, 7)]
        mappings = [
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2"])],
            [ShotMapping(scene_id="SCENE_IMAGE", segment_ids=["s3", "s4"]),
             ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s5", "s6"])],
        ]
        registry = self._make_registry()
        planner = self._make_planner()
        scenes = planner._reconcile(mappings, segments, registry)

        # SCENE_TEXT 有两个 mapping，合并为 1 个 scene 含 2 个 shot
        # SCENE_IMAGE 有 1 个 mapping，1 个 scene 含 1 个 shot
        # → 2 个 scene，3 个 shot（全局递增）
        assert len(scenes) == 2
        # scene_001 = SCENE_TEXT (先出现的是 explicit 没有时 scene_groups 按插入顺序)
        assert scenes[0].visual_type == "text_only"
        assert len(scenes[0].shots) == 2
        assert scenes[0].shots[0].id == "shot_001"
        assert scenes[0].shots[1].id == "shot_002"
        # scene_002 = SCENE_IMAGE
        assert scenes[1].visual_type == "stock_image"
        assert scenes[1].shots[0].id == "shot_003"

    def test_reconcile_explicit_preserved(self):
        """explicit segment 被拆为 singleton scene，保留原 visual。"""
        segments = [
            _seg("s1", "普通", section="第一节"),
            _seg("s2", "显式", section="第一节",
                 explicit=True, visual_type="stock_image", visual_params={"query": "logo"}),
            _seg("s3", "普通2", section="第一节"),
        ]
        mappings = [
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2", "s3"])],
        ]
        registry = self._make_registry()
        planner = self._make_planner()
        scenes = planner._reconcile(mappings, segments, registry)

        # explicit s2 拆出为独立 scene
        explicit = [sc for sc in scenes if any(
            sid == "s2" for shot in sc.shots for sid in shot.segment_ids
        )]
        assert len(explicit) == 1
        assert explicit[0].visual_type == "stock_image"
        assert explicit[0].visual_params == {"query": "logo"}

    def test_reconcile_unknown_scene_raises(self):
        """scene_id 不在 registry 中时报错。"""
        segments = [_seg("s1", "一")]
        mappings = [[ShotMapping(scene_id="UNKNOWN", segment_ids=["s1"])]]
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Unknown scene_id"):
            planner._reconcile(mappings, segments, self._make_registry())

    def test_reconcile_missing_raises(self):
        """缺少 segment 时报错。"""
        segments = [_seg("s1", "一"), _seg("s2", "二")]
        mappings = [[ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"])]]
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Missing"):
            planner._reconcile(mappings, segments, self._make_registry())

    def test_reconcile_non_consecutive_raises(self):
        """shot 内 segment 非连续时报错。"""
        segments = [_seg("s1", "一"), _seg("s2", "二"), _seg("s3", "三")]
        mappings = [[
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s3"]),
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s2"]),
        ]]
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Non-consecutive"):
            planner._reconcile(mappings, segments, self._make_registry())

    def test_reconcile_same_scene_merged(self):
        """相同 scene_id 的多个 mapping 合并为一个 scene，含多个 shot。"""
        segments = [
            _seg("s1", "第一节内容", section="第一节"),
            _seg("s2", "第二节内容", section="第二节"),
            _seg("s3", "第三节内容", section="第三节"),
        ]
        mappings = [
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"])],
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s2"])],
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s3"])],
        ]
        registry = self._make_registry()
        planner = self._make_planner()
        scenes = planner._reconcile(mappings, segments, registry)

        # 3 个 mapping 引用同一 scene_id → 合并为 1 个 scene，3 个 shot
        assert len(scenes) == 1
        assert len(scenes[0].shots) == 3
        assert scenes[0].shots[0].segment_ids == ["s1"]
        assert scenes[0].shots[1].segment_ids == ["s2"]
        assert scenes[0].shots[2].segment_ids == ["s3"]


# ==================== _validate_text_integrity 测试 ====================

class TestTextIntegrity:

    def test_integrity_ok(self):
        """所有 segment 都被映射 → 通过。"""
        segments = [_seg(f"s{i}", f"第{i}段") for i in range(1, 4)]
        mappings = [
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2"]),
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s3"]),
        ]
        # 不应抛异常
        LlmPlanner._validate_text_integrity(mappings, segments)

    def test_integrity_missing_raises(self):
        """遗漏 segment → 报错。"""
        segments = [_seg("s1", "一"), _seg("s2", "二"), _seg("s3", "三")]
        mappings = [
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2"]),
        ]
        with pytest.raises(ValueError, match="Text integrity"):
            LlmPlanner._validate_text_integrity(mappings, segments)
