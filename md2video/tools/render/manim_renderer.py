"""
ManifestDrivenScene - 基于 PlanManifest + ExecutionAssets 的 Manim 场景。

用法 (在 anim/ 目录下运行):
    MD2VIDEO_PLAN_PATH=../artifacts/plan.json \
    MD2VIDEO_EXECUTION_ASSETS_PATH=../artifacts/execution-assets.json \
    MD2VIDEO_TIMELINE_PATH=../artifacts/timeline.json \
    manim -pql manim_renderer.py ManifestDrivenScene
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from manim import FadeOut, ManimColor, config
from manim_voiceover import VoiceoverScene

from md2video.manifest.schema import (
    PlanManifest,
    ResultManifest,
)
from md2video.style.manim_realizer import ManimRealizer
from md2video.style.motifs import create_motif
from md2video.style.packs import DEFAULT_PACK_NAME, get_pack
from md2video.tools.render.manifest_loader import load_manifests_from_env, required_env_value
from md2video.tools.render.timeline_builder import ShotTimelineWriter, TimelineWriter
from md2video.tools.render.cached_voice import CachedVoiceService
from md2video.tools.render.manim_renderer_inputs import (
    TITLE_SEGMENT_TYPES,
    TitleLayoutPart,
    compute_shot_layout,
    iter_shot_render_units,
    segment_render_duration,
    segment_uses_voiceover,
    shot_layout_context,
    title_layout_parts,
    title_layout_positions,
    voiceover_segment_ids,
)
from md2video.config import (
    DEFAULT_TEXT_POSITION, IMAGE_TEXT_POSITION, LEFT_X,
    MAX_CHARS_PER_LINE,
    SUBTITLE_START_Y, SCREEN_BOTTOM, SUBTITLE_SPACING, SUBTITLE_MAX_WIDTH,
)


class ManifestDrivenScene(VoiceoverScene):
    def construct(self):
        plan, result = self._load_manifests()
        self._segment_result_by_id = {seg.id: seg for seg in result.segments}

        self._load_style()

        # 设置语音服务为 CachedVoiceService
        project_root = Path.cwd().parent
        voiced_ids = voiceover_segment_ids(plan)
        if voiced_ids:
            speech_service = CachedVoiceService(
                result,
                project_root=project_root,
                voiced_segment_ids=voiced_ids,
            )
            self._md2video_speech_service = speech_service
            self.set_speech_service(speech_service)
        else:
            self._md2video_speech_service = None

        # 跨 scene 持久状态
        self.timeline = []
        self._timeline_writer = TimelineWriter(self.timeline)
        self.marker_timeline = []
        self.shot_timeline = []
        self._shot_timeline_writer = ShotTimelineWriter(self.shot_timeline)
        self.current_subtitles = []
        self.subtitle_heights = []
        self.is_image_active = False
        self._segment_location_by_id = {}

        # 构建 segment -> scene/shot 映射
        self._all_render_units = list(iter_shot_render_units(plan, include_title_segments=True))
        self._body_render_units = list(iter_shot_render_units(plan))
        self._render_segment_by_segment_id = {}
        self._render_unit_by_segment_id = {}
        self._render_unit_by_shot_id = {}
        self._shot_start_by_shot_id = {}
        for unit in self._all_render_units:
            self._render_unit_by_shot_id.setdefault(unit.shot_id, unit)
            for render_segment in unit.segments:
                self._render_segment_by_segment_id.setdefault(
                    render_segment.segment.id,
                    render_segment,
                )
                self._render_unit_by_segment_id.setdefault(render_segment.segment.id, unit)
                self._segment_location_by_id.setdefault(render_segment.segment.id, {
                    "scene_id": unit.scene_id,
                    "shot_id": unit.shot_id,
                })

        self._construct_by_scenes(plan, result)

    def _load_style(self):
        """加载设计包并实例化 Realizer 与母题（引擎与包正交的唯一接缝）。"""
        pack = get_pack(os.environ.get("MD2VIDEO_STYLE_PACK", DEFAULT_PACK_NAME))
        self._pack = pack
        self._realizer = ManimRealizer(pack, frame_height_px=config.pixel_height)
        print(f"  Style pack: {pack.id}")
        primary_color, secondary_color = self._realizer.motif_colors()
        self._motif = create_motif(
            pack.motif.kind,
            primary_color=primary_color,
            secondary_color=secondary_color,
            transition_duration=self._realizer.transition_duration(),
        )
        # 底色烧在底片里（合成器 v0 不消费 style）
        config.background_color = ManimColor(pack.palette.background)

    def _timeline_entry(
        self,
        seg,
        start: float,
        text: str | None = None,
        end: float | None = None,
        shot_unit=None,
    ) -> dict:
        if shot_unit is not None and (shot_unit.scene_id or shot_unit.shot_id):
            location = {
                "scene_id": shot_unit.scene_id,
                "shot_id": shot_unit.shot_id,
            }
        else:
            location = getattr(self, "_segment_location_by_id", {}).get(seg.id, {})
        entry = {
            "segment_id": seg.id,
            "segment_type": seg.segment_type,
            "text": text if text is not None else seg.text,
            "start": start,
            "end": end,
        }
        entry.update(location)
        return entry

    def _marker_entry(self, cue, shot_unit=None) -> dict:
        location = {
            "scene_id": shot_unit.scene_id if shot_unit is not None else "",
            "shot_id": shot_unit.shot_id if shot_unit is not None else "",
        }
        cue_id = cue.get("id", "")
        entry = {
            "id": cue_id,
            "cue_type": cue.get("cue_type", ""),
            "kind": cue.get("kind", ""),
            "name": cue.get("name", ""),
            "time": self.time,
        }
        entry.update(location)
        return entry

    @contextmanager
    def _voiceover_segment(self, seg, text: str):
        speech_service = getattr(
            self,
            "_md2video_speech_service",
            getattr(self, "speech_service", None),
        )
        if speech_service is None:
            raise RuntimeError(f"No cached speech service for segment {seg.id}")
        with speech_service.voiceover(self, seg.id, text) as tracker:
            yield tracker

    def _find_title_unit(self):
        for unit in self._all_render_units:
            title_main = None
            title_sub = None
            for render_segment in unit.segments:
                seg = render_segment.segment
                if seg.segment_type == "title_main" and title_main is None:
                    title_main = seg
                elif seg.segment_type == "title_sub" and title_sub is None:
                    title_sub = seg
            if title_main or title_sub:
                return unit, title_main, title_sub
        return None, None, None

    def _append_timeline_entry(
        self,
        seg,
        start: float,
        text: str | None = None,
        shot_unit=None,
    ) -> int:
        return self._timeline_writer.append(
            self._timeline_entry(seg, start, text=text, shot_unit=shot_unit)
        )

    def _close_timeline_entry(self, timeline_index: int, end: float | None = None) -> None:
        self._timeline_writer.close(timeline_index, self.time if end is None else end)

    def _construct_by_scenes(self, plan, result):
        """Render in scene/shot order."""
        # 渲染标题
        title_unit, title_main, title_sub = self._find_title_unit()
        if title_main or title_sub:
            title_start = self.time
            self._render_title(title_main, title_sub, title_unit)
            self._setup_motif_after_title()
            if title_unit is not None and all(
                item.segment.segment_type in TITLE_SEGMENT_TYPES
                for item in title_unit.segments
            ):
                self._append_shot_timeline_entry(title_unit, title_start, self.time)
            elif title_unit is not None:
                self._shot_start_by_shot_id[title_unit.shot_id] = title_start
        else:
            # 无标题时仍需初始化母题（母题圆点只有标题交接后才加入场景）
            self._setup_motif_after_title()

        # 按 scene/shot 顺序渲染正文；标题 segment 已在标题卡片中渲染一次。
        for shot_unit in self._body_render_units:
            self._render_shot_unit(shot_unit)

        self._finish()

    def _append_shot_timeline_entry(self, shot_unit, start: float, end: float) -> None:
        full_unit = getattr(self, "_render_unit_by_shot_id", {}).get(
            shot_unit.shot_id,
            shot_unit,
        )
        self._shot_timeline_writer.upsert({
            "shot_id": shot_unit.shot_id,
            "scene_id": shot_unit.scene_id,
            "segment_ids": full_unit.segment_ids,
            "layout_type": full_unit.layout_type,
            "start": start,
            "end": end,
        })

    def _render_shot_unit(self, shot_unit):
        """Render one continuous shot execution unit."""
        shot_start = self._shot_start_by_shot_id.pop(shot_unit.shot_id, self.time)
        layout_ctx = shot_layout_context(shot_unit, config.frame_width, config.frame_height)
        self._process_cues(shot_unit, "start")
        for render_segment in shot_unit.segments:
            segment_id = render_segment.segment.id
            self._process_cues(shot_unit, "before", segment_id)
            self._render_segment(render_segment, shot_unit, layout_ctx)
            self._process_cues(shot_unit, "after", segment_id)
        self._process_cues(shot_unit, "end")
        self._append_shot_timeline_entry(shot_unit, shot_start, self.time)

    def _process_cues(
        self,
        shot_unit,
        position: str,
        anchor_segment_id: str = "",
    ) -> None:
        for cue in shot_unit.cues:
            if cue.get("position", "start") != position:
                continue
            if anchor_segment_id and cue.get("anchor_segment_id", "") != anchor_segment_id:
                continue
            self._process_cue(cue, shot_unit)

    def _process_cue(self, cue, shot_unit) -> None:
        cue_type = cue.get("cue_type", "")
        if cue_type == "marker_image":
            self.marker_timeline.append(self._marker_entry(cue, shot_unit))
            kind = cue.get("kind", "")
            if kind == "start" and not self.is_image_active:
                self.is_image_active = True
                if self._motif is not None:
                    self._motif.dodge(self, "image")
            elif kind == "end" and self.is_image_active:
                self.is_image_active = False
                if self._motif is not None:
                    self._motif.dodge(self, "default")
            return

        if cue_type == "marker_music":
            self.marker_timeline.append(self._marker_entry(cue, shot_unit))

    def _render_segment(self, render_segment, shot_unit, layout_ctx=None):
        """Render a single visible segment inside a shot."""
        seg = render_segment.segment
        stype = seg.segment_type

        if stype == "section_header":
            self._render_section_header(seg, shot_unit, layout_ctx)
            return

        if stype in ("content", "appendix"):
            line = seg.text
            wrapped_line = "\n".join(
                [line[i:i + MAX_CHARS_PER_LINE] for i in range(0, len(line), MAX_CHARS_PER_LINE)]
            )
            start_t = self.time
            text_position, max_text_width = self._content_text_placement(layout_ctx)
            sentence = self._realizer.text(wrapped_line, role="body").move_to(text_position)
            if max_text_width is not None and sentence.width > max_text_width:
                sentence.scale(max_text_width / sentence.width)
            timeline_index = self._append_timeline_entry(seg, start_t, text=line, shot_unit=shot_unit)
            motion = self._realizer.tokens.motion
            if segment_uses_voiceover(seg):
                with self._voiceover_segment(seg, line):
                    self._apply_reveal(motion.body_reveal, sentence)
            else:
                self._apply_reveal(motion.body_reveal, sentence)
                self.wait(self._segment_duration(
                    seg,
                    default=self._realizer.silent_pace("body"),
                ))
            self._apply_dismiss(motion.body_dismiss, sentence)
            self._close_timeline_entry(timeline_index)

    def _apply_reveal(self, intent: str, mobject) -> None:
        """按动效意图出现；意图翻译成 None 时静默 add。"""
        animation = self._realizer.reveal(intent, mobject)
        if animation is None:
            self.add(mobject)
        else:
            self.play(animation)

    def _apply_dismiss(self, intent: str, mobject) -> None:
        """按动效意图移除；意图翻译成 None 时静默 remove。"""
        animation = self._realizer.dismiss(intent, mobject)
        if animation is None:
            self.remove(mobject)
        else:
            self.play(animation)

    def _content_text_placement(self, layout_ctx):
        """Choose position and max width for a body sentence.

        Text lives in the layout's body/text/caption region. Layouts without an
        image region keep the legacy marker-image text shift; layouts that own
        an image region keep text inside its region because the overlay stays
        in the image region.
        """
        if layout_ctx is None or layout_ctx.body is None:
            return (
                IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
            ), None
        if self.is_image_active and not layout_ctx.has_image_region:
            return IMAGE_TEXT_POSITION, None
        return list(layout_ctx.body.center), layout_ctx.body.max_width

    def _segment_duration(self, seg, default: float) -> float:
        result = getattr(self, "_segment_result_by_id", {}).get(seg.id)
        return segment_render_duration(seg, result, default=default)

    def _render_section_header(self, seg, shot_unit=None, layout_ctx=None):
        """渲染 section header（左侧字幕堆叠，装进模板的堆叠子 region）。"""
        timeline = self.timeline
        current_subtitles = self.current_subtitles
        subtitle_heights = self.subtitle_heights
        spacing = SUBTITLE_SPACING
        motion = self._realizer.tokens.motion

        # 堆叠边界来自模板子构图 region（section_stack）；没有子 region 的
        # 布局回退到 body/text/caption placement，仍无 layout 时用 legacy 常量。
        region = None
        if layout_ctx is not None:
            region = layout_ctx.section_stack or layout_ctx.body
        if region is not None:
            max_subtitle_width = min(SUBTITLE_MAX_WIDTH, region.max_width)
            region_left = region.center[0] - region.max_width / 2
            region_top = region.center[1] + region.max_height / 2
            region_bottom = region.center[1] - region.max_height / 2
        else:
            max_subtitle_width = SUBTITLE_MAX_WIDTH
            region_left = LEFT_X
            region_top = SUBTITLE_START_Y
            region_bottom = SCREEN_BOTTOM

        subtitle_text = seg.text
        start_t = self.time
        subtitle = self._realizer.text(subtitle_text, role="section_header")
        if subtitle.width > max_subtitle_width:
            subtitle.scale(max_subtitle_width / subtitle.width)
        subtitle.move_to(region.center if region is not None else DEFAULT_TEXT_POSITION)
        if segment_uses_voiceover(seg):
            with self._voiceover_segment(seg, subtitle_text):
                self._apply_reveal(motion.section_reveal, subtitle)
        else:
            self._apply_reveal(motion.section_reveal, subtitle)
            self.wait(self._segment_duration(
                seg,
                default=self._realizer.silent_pace("section_header"),
            ))
        timeline_index = self._append_timeline_entry(
            seg,
            start_t,
            text=subtitle_text,
            shot_unit=shot_unit,
        )
        subtitle._md2video_timeline_index = timeline_index

        if len(subtitle_text) > 5:
            wrapped_text = "\n".join(
                [subtitle_text[i:i + 5] for i in range(0, len(subtitle_text), 5)]
            )
            wrapped_subtitle = self._realizer.text(
                wrapped_text, role="section_header_detail", line_spacing=0.5,
            )
            if wrapped_subtitle.width > max_subtitle_width:
                wrapped_subtitle.scale(max_subtitle_width / wrapped_subtitle.width)
            wrapped_subtitle._md2video_timeline_index = timeline_index
            self.play(FadeOut(subtitle))
            subtitle = wrapped_subtitle

        subtitle_height = subtitle.height
        need_to_remove = False
        if current_subtitles:
            last_subtitle = current_subtitles[-1]
            last_bottom = last_subtitle.get_bottom()[1]
            new_y = last_bottom - subtitle_height - spacing
            new_bottom = new_y - subtitle_height / 2
            if new_bottom < region_bottom:
                need_to_remove = True

        if need_to_remove and current_subtitles:
            rem = current_subtitles.pop(0)
            subtitle_heights.pop(0)
            self._apply_dismiss(motion.section_dismiss, rem)
            rem_timeline_index = getattr(rem, "_md2video_timeline_index", None)
            if rem_timeline_index is not None:
                self._close_timeline_entry(rem_timeline_index)
            animations = []
            current_y = region_top - current_subtitles[0].height / 2
            for s in current_subtitles:
                animations.append(s.animate.move_to([region_left + s.width / 2, current_y, 0]))
                current_y -= s.height + spacing
            if animations:
                self.play(*animations, run_time=0.5)

        if current_subtitles:
            last_subtitle = current_subtitles[-1]
            new_y = last_subtitle.get_bottom()[1] - subtitle.height / 2 - spacing
        else:
            new_y = region_top - subtitle.height / 2

        self.play(subtitle.animate.move_to([region_left + subtitle.width / 2, new_y, 0]), run_time=1)
        current_subtitles.append(subtitle)
        subtitle_heights.append(subtitle_height)

    def _render_title(self, title_seg, subtitle_seg, shot_unit=None):
        """渲染标题卡片。"""
        title_parts = self._title_parts_for_unit(title_seg, subtitle_seg, shot_unit)

        if not title_parts:
            self._title_mobjects = []
            return

        reveal_intent = self._realizer.tokens.motion.title_reveal
        title_mobjects = []
        instant_adds = []
        animations = []
        start_t = self.time
        for seg, font_size, position in title_parts:
            mobject = self._realizer.text(seg.text, role=seg.segment_type).move_to(position)
            timeline_index = self._append_timeline_entry(
                seg,
                start_t,
                text=seg.text,
                shot_unit=shot_unit,
            )
            title_mobjects.append({
                "mobject": mobject,
                "timeline_index": timeline_index,
                "segment_type": seg.segment_type,
            })
            animation = self._realizer.reveal(reveal_intent, mobject)
            if animation is None:
                instant_adds.append(mobject)
            else:
                animations.append(animation)

        if instant_adds:
            self.add(*instant_adds)
        if animations:
            self.play(*animations)
        self.wait(self._realizer.silent_pace("title_hold"))
        self._title_mobjects = title_mobjects

    def _title_parts_for_unit(self, title_seg, subtitle_seg, shot_unit):
        """Title card parts, placed inside the layout title region when present."""
        if title_seg is None and subtitle_seg is None:
            return []
        main_font_size = self._realizer.font_size("title_main")
        sub_font_size = self._realizer.font_size("title_sub")
        if shot_unit is not None:
            computed = compute_shot_layout(shot_unit)
            positions = title_layout_positions(computed, config.frame_width, config.frame_height)
            if positions is not None:
                parts = []
                if title_seg is not None:
                    parts.append(TitleLayoutPart(title_seg, main_font_size, positions["main"]))
                if subtitle_seg is not None:
                    parts.append(TitleLayoutPart(subtitle_seg, sub_font_size, positions["sub"]))
                return parts
        return title_layout_parts(
            title_seg,
            subtitle_seg,
            main_font_size=main_font_size,
            sub_font_size=sub_font_size,
        )

    def _setup_motif_after_title(self):
        """母题初始化与标题交接（保持原 _setup_dot_animation 的时点与顺序）。"""
        if self._motif is None:
            return
        self._motif.setup(self)
        title_mobjects = getattr(self, "_title_mobjects", [])
        if not title_mobjects:
            return
        slot_by_segment_type = {"title_main": 0, "title_sub": 1}
        pairs = [
            (item["mobject"], slot_by_segment_type.get(item["segment_type"], 0))
            for item in title_mobjects
        ]
        self._motif.play_title_handoff(self, pairs)
        for item in title_mobjects:
            self._close_timeline_entry(item["timeline_index"])
        self._title_mobjects = []

    def _finish(self):
        """收尾：清除字幕和母题，保存 timeline。"""
        for s in self.current_subtitles:
            timeline_index = getattr(s, "_md2video_timeline_index", None)
            if timeline_index is not None:
                self._close_timeline_entry(timeline_index)
        if self.current_subtitles:
            dismiss_animations = [
                self._realizer.dismiss(
                    self._realizer.tokens.motion.section_dismiss, s,
                )
                for s in self.current_subtitles
            ]
            self.play(*[anim for anim in dismiss_animations if anim is not None])

        if self._motif is not None:
            self._motif.teardown(self)

        timeline_path = Path(required_env_value("MD2VIDEO_TIMELINE_PATH"))
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump({"text": self.timeline, "markers": self.marker_timeline, "shots": self.shot_timeline},
                       f, ensure_ascii=False, indent=2)
        print(f"Timeline saved: {timeline_path}")

    def _load_manifests(self) -> tuple[PlanManifest, ResultManifest]:
        """Load explicit PlanManifest and ExecutionAssets renderer inputs."""
        return load_manifests_from_env()
