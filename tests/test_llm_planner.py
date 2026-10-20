"""Tests for LLM Planner — 纯单元测试，不调用 LLM API。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from md2video.manifest.schema import SegmentPlan
from md2video.core.planner.llm_planner import (
    BLUEPRINT_SYSTEM_PROMPT,
    LlmPlanner,
    SceneTemplate, BlueprintOutput, ShotMapping, ChunkMappingOutput,
    strip_openai_prefix,
)


def _seg(id, text, stype="content", section="", **kw):
    return SegmentPlan(id=id, text=text, segment_type=stype, section_context=section, **kw)


# ==================== 模型名前缀 ====================

def test_strip_openai_prefix_strips_documented_prefix():
    assert strip_openai_prefix("openai:gpt-4o") == "gpt-4o"


def test_strip_openai_prefix_accepts_bare_name():
    assert strip_openai_prefix("gpt-4o") == "gpt-4o"


def test_strip_openai_prefix_case_insensitive():
    assert strip_openai_prefix("OpenAI:gpt-4o") == "gpt-4o"


def test_strip_openai_prefix_keeps_colon_in_model_name():
    """Ollama 等兼容网关的模型名自带冒号（llama3:8b），不能当 provider 前缀剥。"""
    assert strip_openai_prefix("llama3:8b") == "llama3:8b"


def test_strip_openai_prefix_keeps_slash_names():
    assert strip_openai_prefix("z-ai/glm-5-turbo") == "z-ai/glm-5-turbo"


def test_constructor_normalizes_model_name():
    planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
    assert planner._model_name == "gpt-4o"


# ==================== plan() 集成测试 ====================

def test_blueprint_prompt_does_not_offer_manim_as_visual_type():
    visual_type_line = next(
        line
        for line in BLUEPRINT_SYSTEM_PROMPT.splitlines()
        if "visual_type: one of" in line
    )

    assert "manim" not in visual_type_line
    assert "stock_video" not in BLUEPRINT_SYSTEM_PROMPT


class TestPlan:

    def test_empty_input(self):
        planner = LlmPlanner(model="openai:gpt-4o", api_key="test-key")
        assert planner.plan([]) == []


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
                layout_type="image_top_text_bottom",
                layout_params={"split": "image_focus"},
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
        assert scenes[1].layout_type == "image_top_text_bottom"
        assert scenes[1].layout_params == {"split": "image_focus"}

    def test_reconcile_sequential_ids(self):
        """多 chunk 的 A/B/A 切换保序；回到 A 时复用场景身份。"""
        segments = [_seg(f"s{i}", f"第{i}段") for i in range(1, 7)]
        mappings = [
            [ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1", "s2"])],
            [ShotMapping(scene_id="SCENE_IMAGE", segment_ids=["s3", "s4"]),
             ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s5", "s6"])],
        ]
        registry = self._make_registry()
        planner = self._make_planner()
        scenes = planner._reconcile(mappings, segments, registry)

        assert len(scenes) == 3
        assert [scene.visual_type for scene in scenes] == [
            "text_only", "stock_image", "text_only",
        ]
        assert [scene.id for scene in scenes] == [
            "scene_001", "scene_002", "scene_001",
        ]
        assert [shot.id for scene in scenes for shot in scene.shots] == [
            "shot_001", "shot_002", "shot_003",
        ]
        assert [sid for scene in scenes for sid in scene.all_segment_ids] == [
            segment.id for segment in segments
        ]

    def test_reconcile_explicit_preserved(self):
        """explicit segment 被拆为 singleton scene；v2 起 segment 不携带
        visual/layout 字段，singleton scene 使用默认值。"""
        segments = [
            _seg("s1", "普通", section="第一节"),
            _seg("s2", "显式", section="第一节", explicit=True),
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
        assert explicit[0].visual_type == "text_only"
        assert explicit[0].visual_params == {}
        assert explicit[0].layout_type == "center_title_body"
        assert [scene.all_segment_ids for scene in scenes] == [["s1"], ["s2"], ["s3"]]
        assert scenes[0].id == scenes[2].id != scenes[1].id

    def test_reconcile_unknown_scene_raises(self):
        """scene_id 不在 registry 中时报错。"""
        segments = [_seg("s1", "一")]
        mappings = [[ShotMapping(scene_id="UNKNOWN", segment_ids=["s1"])]]
        planner = self._make_planner()
        with pytest.raises(ValueError, match="Unknown scene_id"):
            planner._reconcile(mappings, segments, self._make_registry())

    def test_reconcile_invalid_registry_layout_raises(self):
        segments = [_seg("s1", "one")]
        mappings = [[ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"])]]
        registry = self._make_registry()
        registry[0] = registry[0].model_copy(update={"layout_type": "missing_layout"})
        planner = self._make_planner()

        with pytest.raises(ValueError, match="Unknown layout_type"):
            planner._reconcile(mappings, segments, registry)

    def test_reconcile_invalid_registry_layout_params_raises(self):
        segments = [_seg("s1", "one")]
        mappings = [[ShotMapping(scene_id="SCENE_IMAGE", segment_ids=["s1"])]]
        registry = self._make_registry()
        registry[1] = registry[1].model_copy(update={"layout_params": {"split": "giant"}})
        planner = self._make_planner()

        with pytest.raises(ValidationError, match="split"):
            planner._reconcile(mappings, segments, registry)

    def test_reconcile_rejects_manim_visual_type(self):
        segments = [_seg("s1", "one")]
        mappings = [[ShotMapping(scene_id="SCENE_MANIM", segment_ids=["s1"])]]
        registry = [
            SceneTemplate(
                id="SCENE_MANIM",
                name="Manim",
                description="render backend by mistake",
                visual_type="manim",
            ),
        ]
        planner = self._make_planner()

        with pytest.raises(ValueError, match="Unsupported visual_type.*SCENE_MANIM.*manim"):
            planner._reconcile(mappings, segments, registry)

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

    def test_reconcile_rejects_reordered_shots(self):
        segments = [_seg("s1", "one"), _seg("s2", "two")]
        mappings = [[
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s2"]),
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"]),
        ]]
        with pytest.raises(ValueError, match="order"):
            self._make_planner()._reconcile(mappings, segments, self._make_registry())

    def test_reconcile_rejects_empty_shot(self):
        mappings = [[
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=[]),
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"]),
        ]]
        with pytest.raises(ValueError, match="Empty shot"):
            self._make_planner()._reconcile(mappings, [_seg("s1", "one")], self._make_registry())

    def test_reconcile_explicit_between_segments_does_not_join_nonconsecutive_text(self):
        segments = [_seg(f"s{i}", str(i), explicit=i in (2, 4)) for i in range(1, 6)]
        mappings = [[ShotMapping(scene_id="SCENE_IMAGE", segment_ids=[s.id for s in segments])]]
        scenes = self._make_planner()._reconcile(mappings, segments, self._make_registry())
        assert [scene.all_segment_ids for scene in scenes] == [[f"s{i}"] for i in range(1, 6)]
        assert [scene.visual_type for scene in scenes] == [
            "stock_image", "text_only", "stock_image", "text_only", "stock_image",
        ]
        assert scenes[0].id == scenes[2].id == scenes[4].id

    def test_plan_falls_back_when_model_reorders_text(self, monkeypatch):
        planner = self._make_planner()
        segments = [_seg("s1", "one"), _seg("s2", "two")]
        monkeypatch.setattr(planner, "_global_blueprint", lambda _: self._make_registry())
        monkeypatch.setattr(planner, "_chunk_mapping", lambda *_: [
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s2"]),
            ShotMapping(scene_id="SCENE_TEXT", segment_ids=["s1"]),
        ])
        scenes = planner.plan(segments)
        assert [sid for scene in scenes for sid in scene.all_segment_ids] == ["s1", "s2"]

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
