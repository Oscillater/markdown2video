"""LLM Planner — 两阶段全局导演方案。
第一阶段（全局定调）：输入完整 Markdown，产出 Scene Registry（3~5 个 Scene 模板）。
第二阶段（局部分镜）：按章节分块，每块独立调 LLM 映射 shot → scene。
框架层重组校验，保证文本完整性。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from md2video.manifest.schema import ScenePlan, SegmentPlan, ShotPlan
from md2video.core.planner.rule_planner import (
    RulePlanner,
    attach_marker_cues_to_shots,
    renderable_segments,
)
from md2video.config import RENDER_BACKEND_ONLY_VISUAL_TYPES
from md2video.layout import create_default_layout_registry
from md2video.layout.schema import DEFAULT_LAYOUT_TYPE


# ==================== 两阶段数据结构 ====================

class SceneTemplate(BaseModel):
    """第一阶段产出的 Scene 模板（视觉资产库条目）。"""
    id: str                          # e.g. "SCENE_CONCEPT"
    name: str                        # e.g. "科技概念讲解"
    description: str                 # LLM 对该风格的描述
    visual_type: str                 # text_only / stock_image / stock_video
    visual_params: Dict = Field(default_factory=dict)
    layout_type: str = DEFAULT_LAYOUT_TYPE
    layout_params: Dict = Field(default_factory=dict)


class BlueprintOutput(BaseModel):
    """第一阶段输出：Scene Registry。"""
    scene_templates: List[SceneTemplate] = Field(min_length=1)


class ShotMapping(BaseModel):
    """第二阶段输出的 shot-scene 映射。"""
    scene_id: str                    # 引用 BlueprintOutput 中的 SceneTemplate.id
    segment_ids: List[str]


class ChunkMappingOutput(BaseModel):
    """第二阶段输出：一个 chunk 的完整映射。"""
    shots: List[ShotMapping] = Field(min_length=1)


# ==================== 两阶段 Prompt ====================

BLUEPRINT_SYSTEM_PROMPT = """\
You are a video director. Given a complete script (Markdown), define 3~5 scene \
templates (visual style classes) for the video.

For each template, decide:
- id: short uppercase identifier (e.g. SCENE_CONCEPT, SCENE_NARRATIVE)
- name: short Chinese name (e.g. "概念讲解", "叙事抒情")
- description: what kind of content this style is for
- visual_type: one of [text_only, stock_image, stock_video]
- visual_params: if stock_image/stock_video, include "query" with English keywords; \
optionally include "preferred_provider" as a suggested provider name (e.g. "pexels")
- layout_type: one of [center_title_body, full_bleed_image_caption_bottom, \
image_top_text_bottom]. Use center_title_body unless image placement is essential.
- layout_params: optional finite template options only; never include pixel coordinates.

Rules:
1. text_only is for abstract/analytical content with no clear visual
2. stock_image is for content that benefits from a related photo/illustration
3. stock_video is for dynamic/action content that needs motion
4. Chinese classical text (古文) often works well with text_only or subtle stock_image
5. You MUST call the submit_blueprint tool to submit your result."""


def _build_blueprint_user_prompt(markdown_text: str) -> str:
    return (
        "Here is the complete script:\n\n"
        f"{markdown_text}\n\n"
        "Define 3~5 scene templates for this video. "
        "Think about what visual styles best serve the content."
    )


CHUNK_MAPPING_SYSTEM_PROMPT = """\
You are a video planner doing shot-level mapping for one section of a script.

You are given:
1. A list of text segments (in order, with IDs)
2. A Scene Registry: the available visual styles to choose from

Your task:
- Group consecutive segments into shots (continuous visual units)
- Assign each shot to ONE scene from the registry (by scene_id)
- Every segment must appear in exactly one shot, no gaps, no duplicates

Rules:
1. Shots contain consecutive segments in the order given
2. Multiple consecutive shots can reference the same scene_id
3. [EXPLICIT] tagged segments will be handled by the system — just include them normally
4. You MUST call the submit_chunk_mapping tool to submit your result."""


def _build_chunk_mapping_user_prompt(
    segments: List[SegmentPlan], registry: List[SceneTemplate],
) -> str:
    seg_lines = []
    for seg in segments:
        tag = " [EXPLICIT]" if seg.explicit else ""
        seg_lines.append(f"  {seg.id}: [{seg.segment_type}]{tag} \"{seg.text}\"")

    registry_lines = []
    for tmpl in registry:
        vp = ", ".join(f"{k}={v}" for k, v in tmpl.visual_params.items()) or "(none)"
        registry_lines.append(
            f"  {tmpl.id}: \"{tmpl.name}\" — {tmpl.description} "
            f"[{tmpl.visual_type}, {vp}, layout={tmpl.layout_type}]"
        )

    return (
        "Segments (in order):\n"
        + "\n".join(seg_lines)
        + "\n\nAvailable Scene Registry:\n"
        + "\n".join(registry_lines)
        + "\n\nGroup these segments into shots and assign each shot a scene_id "
        "from the registry."
    )


# ==================== LLM Planner ====================

class LlmPlanner:
    """两阶段语义规划器：全局定调 → 局部分镜 → 框架重组校验。

    任何失败自动 fallback 到 RulePlanner。
    """

    def __init__(self, model: str = "openai:gpt-4o", api_key: str = "", base_url: str = ""):
        from pydantic_ai import Agent
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.models.openai import OpenAIChatModel

        provider = OpenAIProvider(
            api_key=api_key or None,
            base_url=base_url or None,
        )
        ai_model = OpenAIChatModel(model, provider=provider)
        self._layout_registry = create_default_layout_registry()

        # 第一阶段 agent：全局定调
        self._blueprint_agent = Agent(
            ai_model,
            instructions=BLUEPRINT_SYSTEM_PROMPT,
            retries=1,
        )
        self._blueprint_output: BlueprintOutput | None = None

        @self._blueprint_agent.tool_plain
        def submit_blueprint(templates: List[Dict]) -> str:
            """提交场景模板列表。每个模板包含 id, name, description, visual_type, visual_params。"""
            parsed = []
            for t in templates:
                template = SceneTemplate(
                    id=t["id"],
                    name=t["name"],
                    description=t["description"],
                    visual_type=t.get("visual_type", "text_only"),
                    visual_params=t.get("visual_params", {}),
                    layout_type=t.get("layout_type", DEFAULT_LAYOUT_TYPE),
                    layout_params=t.get("layout_params", {}),
                )
                self._layout_registry.validate(
                    template.layout_type,
                    template.layout_params,
                )
                parsed.append(template)
            self._blueprint_output = BlueprintOutput(scene_templates=parsed)
            return "Blueprint submitted successfully."

        # 第二阶段 agent：局部分镜
        self._mapping_agent = Agent(
            ai_model,
            instructions=CHUNK_MAPPING_SYSTEM_PROMPT,
            retries=1,
        )
        self._chunk_output: ChunkMappingOutput | None = None

        @self._mapping_agent.tool_plain
        def submit_chunk_mapping(shots: List[Dict]) -> str:
            """提交 shot-scene 映射。每个 shot 包含 scene_id 和 segment_ids。"""
            parsed = [
                ShotMapping(scene_id=s["scene_id"], segment_ids=s["segment_ids"])
                for s in shots
            ]
            self._chunk_output = ChunkMappingOutput(shots=parsed)
            return "Chunk mapping submitted successfully."

        self._fallback = RulePlanner()

    # ==================== 分块逻辑 ====================

    @staticmethod
    def _split_chunks(
        segments: List[SegmentPlan], max_segs: int = 30,
    ) -> List[List[SegmentPlan]]:
        """按 section_context 分块，title 类型归入首块，超长块按 max_segs 再拆。"""
        if not segments:
            return []

        TITLE_TYPES = frozenset({"title_main", "title_sub"})
        chunks: List[List[SegmentPlan]] = []
        current_chunk: List[SegmentPlan] = []
        current_context = ""

        def flush():
            nonlocal current_chunk
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []

        for seg in segments:
            # title 类型始终归入第一个 chunk
            if seg.segment_type in TITLE_TYPES:
                current_chunk.append(seg)
                continue

            # section 变化时切分
            if seg.section_context != current_context and current_chunk:
                # 检查当前 chunk 是否已有非 title 内容
                has_content = any(s.segment_type not in TITLE_TYPES for s in current_chunk)
                if has_content:
                    flush()

            current_context = seg.section_context

            # 单 chunk 超 max_segs 时强制切分
            if len(current_chunk) >= max_segs:
                flush()

            current_chunk.append(seg)

        flush()

        # 如果只有 title chunk 且后面没有内容，合并
        if len(chunks) > 1:
            title_only = all(
                s.segment_type in TITLE_TYPES for s in chunks[0]
            )
            if title_only:
                chunks[1] = chunks[0] + chunks[1]
                chunks.pop(0)

        return chunks if chunks else [segments]

    def plan(self, segments: List[SegmentPlan]) -> List[ScenePlan]:
        if not segments:
            return []
        try:
            return self._plan_two_pass(segments)
        except Exception as e:
            print(f"  [LLM Planner] {type(e).__name__}: {e}")
            print("  [LLM Planner] Falling back to Rule Planner")
            return self._fallback.plan(segments)

    # ==================== 两阶段核心流程 ====================

    def _plan_two_pass(self, segments: List[SegmentPlan]) -> List[ScenePlan]:
        """两阶段方案：全局定调 → 分块 → 局部分镜 → 重组校验。"""
        renderable = renderable_segments(segments)
        if not renderable:
            return attach_marker_cues_to_shots(segments, [])

        # 第一阶段：全局定调
        registry = self._global_blueprint(renderable)
        print(f"  [LLM Planner] Blueprint: {len(registry)} scene templates")

        # 分块
        chunks = self._split_chunks(renderable)
        print(f"  [LLM Planner] Split into {len(chunks)} chunks")

        # 第二阶段：逐块局部分镜
        all_mappings: List[List[ShotMapping]] = []
        for i, chunk in enumerate(chunks):
            mapping = self._chunk_mapping(chunk, registry)
            print(f"  [LLM Planner] Chunk {i+1}/{len(chunks)}: {len(mapping)} shots")
            all_mappings.append(mapping)

        # 第三阶段：框架重组校验
        scenes = self._reconcile(all_mappings, renderable, registry)
        return attach_marker_cues_to_shots(segments, scenes)

    def _global_blueprint(self, segments: List[SegmentPlan]) -> List[SceneTemplate]:
        """第一阶段：输入完整 Markdown 原文，产出 Scene Registry。"""
        self._blueprint_output = None
        markdown_text = "\n".join(seg.text for seg in segments)
        user_prompt = _build_blueprint_user_prompt(markdown_text)
        self._blueprint_agent.run_sync(user_prompt)
        if self._blueprint_output is None:
            raise ValueError("LLM did not call submit_blueprint tool")
        return self._blueprint_output.scene_templates

    def _chunk_mapping(
        self, chunk: List[SegmentPlan], registry: List[SceneTemplate],
    ) -> List[ShotMapping]:
        """第二阶段：输入一个 chunk + Scene Registry，LLM 映射 shot→scene。"""
        self._chunk_output = None
        user_prompt = _build_chunk_mapping_user_prompt(chunk, registry)
        self._mapping_agent.run_sync(user_prompt)
        if self._chunk_output is None:
            raise ValueError("LLM did not call submit_chunk_mapping tool")
        return self._chunk_output.shots

    def _reconcile(
        self,
        all_mappings: List[List[ShotMapping]],
        segments: List[SegmentPlan],
        registry: List[SceneTemplate],
    ) -> List[ScenePlan]:
        """第三阶段：合并所有 chunk 映射 → 校验 → explicit 拆分 → 生成 ScenePlan。"""
        seg_map = {s.id: s for s in segments}
        all_seg_ids = set(s.id for s in segments)
        seg_order = [s.id for s in segments]
        registry_map = {t.id: t for t in registry}
        for template in registry:
            if template.visual_type in RENDER_BACKEND_ONLY_VISUAL_TYPES:
                raise ValueError(
                    f"Unsupported visual_type in scene template "
                    f"{template.id}: {template.visual_type}"
                )
            self._layout_registry.validate(
                template.layout_type,
                template.layout_params,
            )

        # 展平所有 chunk 的 mappings
        flat_mappings: List[ShotMapping] = []
        for mappings in all_mappings:
            flat_mappings.extend(mappings)

        # 校验 1: 每个 segment 恰好出现一次
        seen: set[str] = set()
        for mapping in flat_mappings:
            if mapping.scene_id not in registry_map:
                raise ValueError(f"Unknown scene_id: {mapping.scene_id}")
            for sid in mapping.segment_ids:
                if sid in seen:
                    raise ValueError(f"Duplicate segment {sid}")
                if sid not in all_seg_ids:
                    raise ValueError(f"Unknown segment {sid}")
                seen.add(sid)
        missing = all_seg_ids - seen
        if missing:
            raise ValueError(f"Missing segments: {missing}")

        # 校验 2: 每个 shot 内 segment 连续（全局顺序）
        for mapping in flat_mappings:
            indices = [seg_order.index(sid) for sid in mapping.segment_ids]
            for i in range(1, len(indices)):
                if indices[i] != indices[i - 1] + 1:
                    raise ValueError(
                        f"Non-consecutive segments in shot: {mapping.segment_ids}"
                    )

        # 校验 3: 文本完整性 — segment 拼接文本必须覆盖原始文本
        self._validate_text_integrity(flat_mappings, segments)

        # 构建 ScenePlan：按 scene_id 分组合并，同时拆分 explicit
        scenes: List[ScenePlan] = []
        scene_counter = 0
        shot_counter = 0

        # 1. 收集 explicit singleton scenes
        explicit_entries: List[tuple] = []  # (seg_id, seg_plan)
        # 2. 收集 non-explicit 的 mapping，按 scene_id 分组
        from collections import defaultdict
        scene_groups: Dict[str, List[List[str]]] = defaultdict(list)

        for mapping in flat_mappings:
            exp_ids = [sid for sid in mapping.segment_ids if seg_map[sid].explicit]
            non_exp_ids = [sid for sid in mapping.segment_ids if not seg_map[sid].explicit]

            for eid in exp_ids:
                explicit_entries.append((eid, seg_map[eid]))
            if non_exp_ids:
                scene_groups[mapping.scene_id].append(non_exp_ids)

        # 3. 先输出 explicit singleton scenes（按原始顺序）
        explicit_order = {sid: i for i, (sid, _) in enumerate(explicit_entries)}
        for eid, eseg in sorted(explicit_entries, key=lambda x: explicit_order[x[0]]):
            scene_counter += 1
            shot_counter += 1
            scenes.append(ScenePlan(
                id=f"scene_{scene_counter:03d}",
                visual_type=eseg.visual_type,
                visual_params=eseg.visual_params,
                layout_type=eseg.layout_type,
                layout_params=eseg.layout_params,
                section_context=eseg.section_context,
                shots=[ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[eid])],
            ))

        # 4. 按 scene_id 分组输出：每个 scene_id → 一个 ScenePlan（含多个 shot）
        for scene_id, shot_id_groups in scene_groups.items():
            template = registry_map[scene_id]
            shots = []
            for seg_ids in shot_id_groups:
                shot_counter += 1
                shots.append(ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=seg_ids))
            scene_counter += 1
            first_seg = seg_map[shot_id_groups[0][0]]
            scenes.append(ScenePlan(
                id=f"scene_{scene_counter:03d}",
                visual_type=template.visual_type,
                visual_params=template.visual_params,
                layout_type=template.layout_type,
                layout_params=template.layout_params,
                section_context=first_seg.section_context,
                shots=shots,
            ))

        return scenes

    @staticmethod
    def _validate_text_integrity(
        mappings: List[ShotMapping], segments: List[SegmentPlan],
    ) -> None:
        """校验 segment 拼接文本覆盖所有原始文本。"""
        all_mapped_ids = set()
        for m in mappings:
            all_mapped_ids.update(m.segment_ids)
        all_seg_ids = set(s.id for s in segments)
        missing = all_seg_ids - all_mapped_ids
        if missing:
            raise ValueError(f"Text integrity check failed — missing segments: {missing}")

