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
from contextlib import contextmanager
from pathlib import Path

from md2video.manifest.schema import (
    PlanManifest,
    ResultManifest,
)
from md2video.tools.render.manifest_loader import load_manifests_from_env, required_env_value
from md2video.tools.render.timeline_builder import ShotTimelineWriter, TimelineWriter
from md2video.tools.render.cached_voice import CachedVoiceService
from md2video.tools.render.manim_renderer_inputs import (
    TITLE_SEGMENT_TYPES,
    iter_shot_render_units,
    segment_render_duration,
    segment_uses_voiceover,
    title_layout_parts,
    voiceover_segment_ids,
)
from md2video.config import (
    RIGHT_X, DEFAULT_TEXT_POSITION, IMAGE_TEXT_POSITION, LEFT_X,
    DOTS_TRANSITION_TIME, MAX_CHARS_PER_LINE,
    DEFAULT_DOTS_OFFSET, IMAGE_DOTS_OFFSET,
    SUBTITLE_START_Y, SCREEN_BOTTOM, SUBTITLE_SPACING, SUBTITLE_MAX_WIDTH,
    DEFAULT_FONT,
)

from manim import *
import numpy as np
from manim_voiceover import VoiceoverScene


def textWithFont(text, font=DEFAULT_FONT, **kwargs):
    return Text(text, font=font, **kwargs)


class ManifestDrivenScene(VoiceoverScene):
    def construct(self):
        plan, result = self._load_manifests()
        self._segment_result_by_id = {seg.id: seg for seg in result.segments}

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
        if speech_service is not None and hasattr(speech_service, "use_segment"):
            with speech_service.use_segment(seg.id):
                with self.voiceover(text=text) as tracker:
                    yield tracker
        else:
            with self.voiceover(text=text) as tracker:
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
            dots_offset_tracker, dot1, dot2, t_tracker = \
                self._setup_dot_animation(title_main, title_sub)
            if title_unit is not None and all(
                item.segment.segment_type in TITLE_SEGMENT_TYPES
                for item in title_unit.segments
            ):
                self._append_shot_timeline_entry(title_unit, title_start, self.time)
            elif title_unit is not None:
                self._shot_start_by_shot_id[title_unit.shot_id] = title_start
        else:
            # 无标题时仍需初始化点动画
            dots_offset_tracker, dot1, dot2, t_tracker = self._setup_dot_animation(None, None)

        # 按 scene/shot 顺序渲染正文；标题 segment 已在标题卡片中渲染一次。
        for shot_unit in self._body_render_units:
            self._render_shot_unit(shot_unit, dots_offset_tracker)

        self._finish(dot1, dot2, t_tracker)

    def _append_shot_timeline_entry(self, shot_unit, start: float, end: float) -> None:
        full_unit = getattr(self, "_render_unit_by_shot_id", {}).get(
            shot_unit.shot_id,
            shot_unit,
        )
        self._shot_timeline_writer.upsert({
            "shot_id": shot_unit.shot_id,
            "scene_id": shot_unit.scene_id,
            "segment_ids": full_unit.segment_ids,
            "start": start,
            "end": end,
        })

    def _render_shot_unit(self, shot_unit, dots_offset_tracker):
        """Render one continuous shot execution unit."""
        shot_start = self._shot_start_by_shot_id.pop(shot_unit.shot_id, self.time)
        self._process_cues(shot_unit, "start", dots_offset_tracker)
        for render_segment in shot_unit.segments:
            segment_id = render_segment.segment.id
            self._process_cues(shot_unit, "before", dots_offset_tracker, segment_id)
            self._render_segment(render_segment, shot_unit, dots_offset_tracker)
            self._process_cues(shot_unit, "after", dots_offset_tracker, segment_id)
        self._process_cues(shot_unit, "end", dots_offset_tracker)
        self._append_shot_timeline_entry(shot_unit, shot_start, self.time)

    def _process_cues(
        self,
        shot_unit,
        position: str,
        dots_offset_tracker,
        anchor_segment_id: str = "",
    ) -> None:
        for cue in shot_unit.cues:
            if cue.get("position", "start") != position:
                continue
            if anchor_segment_id and cue.get("anchor_segment_id", "") != anchor_segment_id:
                continue
            self._process_cue(cue, shot_unit, dots_offset_tracker)

    def _process_cue(self, cue, shot_unit, dots_offset_tracker) -> None:
        cue_type = cue.get("cue_type", "")
        if cue_type == "marker_image":
            self.marker_timeline.append(self._marker_entry(cue, shot_unit))
            kind = cue.get("kind", "")
            if kind == "start" and not self.is_image_active:
                self.is_image_active = True
                if dots_offset_tracker is not None:
                    self.play(
                        dots_offset_tracker.animate.move_to(IMAGE_DOTS_OFFSET),
                        run_time=DOTS_TRANSITION_TIME,
                    )
            elif kind == "end" and self.is_image_active:
                self.is_image_active = False
                if dots_offset_tracker is not None:
                    self.play(
                        dots_offset_tracker.animate.move_to(DEFAULT_DOTS_OFFSET),
                        run_time=DOTS_TRANSITION_TIME,
                    )
            return

        if cue_type == "marker_music":
            self.marker_timeline.append(self._marker_entry(cue, shot_unit))

    def _render_segment(self, render_segment, shot_unit, dots_offset_tracker):
        """Render a single visible segment inside a shot."""
        seg = render_segment.segment
        stype = seg.segment_type

        if stype == "section_header":
            self._render_section_header(seg, dots_offset_tracker, render_segment, shot_unit)
            return

        if stype in ("content", "appendix"):
            line = seg.text
            wrapped_line = "\n".join(
                [line[i:i + MAX_CHARS_PER_LINE] for i in range(0, len(line), MAX_CHARS_PER_LINE)]
            )
            start_t = self.time
            text_position = IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
            sentence = textWithFont(wrapped_line, font_size=15).move_to(text_position)
            timeline_index = self._append_timeline_entry(seg, start_t, text=line, shot_unit=shot_unit)
            if segment_uses_voiceover(seg):
                with self._voiceover_segment(seg, line) as tracker:
                    self.add(sentence)
                    self._wait_for_voiceover(tracker, seg, render_segment)
            else:
                self.add(sentence)
                self.wait(self._segment_duration(seg, default=2.0, render_segment=render_segment))
            self.remove(sentence)
            self._close_timeline_entry(timeline_index)

    def _segment_duration(self, seg, default: float = 2.0, render_segment=None) -> float:
        item = render_segment or getattr(self, "_render_segment_by_segment_id", {}).get(seg.id)
        result = getattr(self, "_segment_result_by_id", {}).get(seg.id)
        return segment_render_duration(seg, result, item, default=default)

    def _voiceover_duration(self, tracker, seg, render_segment=None) -> float:
        tracker_duration = getattr(tracker, "duration", None)
        if tracker_duration is not None:
            try:
                duration = float(tracker_duration)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
        return self._segment_duration(seg, default=0.0, render_segment=render_segment)

    def _wait_for_voiceover(self, tracker, seg, render_segment=None) -> None:
        duration = self._voiceover_duration(tracker, seg, render_segment)
        if duration > 0:
            self.wait(duration)

    def _render_section_header(self, seg, dots_offset_tracker, render_segment=None, shot_unit=None):
        """渲染 section header（左侧字幕堆叠）。"""
        timeline = self.timeline
        current_subtitles = self.current_subtitles
        subtitle_heights = self.subtitle_heights
        spacing = SUBTITLE_SPACING

        subtitle_text = seg.text
        start_t = self.time
        subtitle = textWithFont(subtitle_text, font_size=20).move_to(DEFAULT_TEXT_POSITION)
        if subtitle.width > SUBTITLE_MAX_WIDTH:
            subtitle.scale(SUBTITLE_MAX_WIDTH / subtitle.width)

        if segment_uses_voiceover(seg):
            with self._voiceover_segment(seg, subtitle_text) as tracker:
                self.play(Write(subtitle))
                self._wait_for_voiceover(tracker, seg, render_segment)
        else:
            self.play(Write(subtitle))
            self.wait(self._segment_duration(seg, default=0.5, render_segment=render_segment))
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
            wrapped_subtitle = textWithFont(wrapped_text, font_size=12, line_spacing=0.5)
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
            if new_bottom < SCREEN_BOTTOM:
                need_to_remove = True

        if need_to_remove and current_subtitles:
            rem = current_subtitles.pop(0)
            subtitle_heights.pop(0)
            self.play(FadeOut(rem))
            rem_timeline_index = getattr(rem, "_md2video_timeline_index", None)
            if rem_timeline_index is not None:
                self._close_timeline_entry(rem_timeline_index)
            animations = []
            current_y = SUBTITLE_START_Y
            for s in current_subtitles:
                animations.append(s.animate.move_to([LEFT_X, current_y, 0]))
                current_y -= s.height + spacing
            if animations:
                self.play(*animations, run_time=0.5)

        if current_subtitles:
            last_subtitle = current_subtitles[-1]
            new_y = last_subtitle.get_bottom()[1] - subtitle.height / 2 - spacing
        else:
            new_y = SUBTITLE_START_Y

        self.play(subtitle.animate.move_to([LEFT_X, new_y, 0]), run_time=1)
        current_subtitles.append(subtitle)
        subtitle_heights.append(subtitle_height)

    def _render_title(self, title_seg, subtitle_seg, shot_unit=None):
        """渲染标题卡片。"""
        title_parts = title_layout_parts(title_seg, subtitle_seg)

        if not title_parts:
            self._title_mobjects = []
            return

        title_mobjects = []
        animations = []
        start_t = self.time
        for seg, font_size, position in title_parts:
            mobject = textWithFont(seg.text, font_size=font_size).move_to(position)
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
            animations.append(Write(mobject))

        self.play(*animations)
        self.wait(1)
        self._title_mobjects = title_mobjects

    def _setup_dot_animation(self, title_main_seg, title_sub_seg):
        """设置点动画并返回 (dots_offset_tracker, dot1, dot2, t_tracker)。"""
        t_tracker = ValueTracker(0)
        t_tracker.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(t_tracker)

        dots_offset_tracker = Dot(point=np.array(DEFAULT_DOTS_OFFSET), stroke_opacity=0, fill_opacity=0)
        self.add(dots_offset_tracker)
        A, B = 0.75, 0.5
        dot1 = Dot(radius=0.04, color=WHITE)
        dot2 = Dot(radius=0.04, color=BLUE)
        dot1.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([
                A * np.sin(1.4 * t_tracker.get_value() - PI / 8),
                B * np.sin(2.1 * t_tracker.get_value()), 0
            ])
        ))
        dot2.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([
                A * np.sin(1.61 * t_tracker.get_value() + PI / 8),
                B * np.sin(1.19 * t_tracker.get_value()), 0
            ])
        ))

        # 变点动画
        title_mobjects = getattr(self, "_title_mobjects", [])
        if title_mobjects:
            dot_by_segment_type = {
                "title_main": dot1,
                "title_sub": dot2,
            }
            self.play(
                *[
                    Transform(item["mobject"], dot_by_segment_type.get(item["segment_type"], dot1))
                    for item in title_mobjects
                ],
                run_time=2
            )
            for item in title_mobjects:
                self._close_timeline_entry(item["timeline_index"])
            self.remove(*[item["mobject"] for item in title_mobjects])
            self.add(dot1, dot2)
            self._title_mobjects = []

        return dots_offset_tracker, dot1, dot2, t_tracker

    def _finish(self, dot1, dot2, t_tracker):
        """收尾：清除字幕和点动画，保存 timeline。"""
        for s in self.current_subtitles:
            timeline_index = getattr(s, "_md2video_timeline_index", None)
            if timeline_index is not None:
                self._close_timeline_entry(timeline_index)
        if self.current_subtitles:
            self.play(*[FadeOut(s) for s in self.current_subtitles])

        self.play(FadeOut(dot1), FadeOut(dot2))
        t_tracker.clear_updaters()

        timeline_path = Path(required_env_value("MD2VIDEO_TIMELINE_PATH"))
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump({"text": self.timeline, "markers": self.marker_timeline, "shots": self.shot_timeline},
                       f, ensure_ascii=False, indent=2)
        print(f"Timeline saved: {timeline_path}")

    def _load_manifests(self) -> tuple[PlanManifest, ResultManifest]:
        """Load explicit PlanManifest and ExecutionAssets renderer inputs."""
        return load_manifests_from_env()
