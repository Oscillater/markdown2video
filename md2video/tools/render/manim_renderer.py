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
from md2video.tools.render.timeline_builder import TimelineWriter, build_shot_timeline
from md2video.tools.render.cached_voice import CachedVoiceService
from md2video.tools.render.manim_renderer_inputs import (
    iter_scene_render_segments,
    segment_uses_voiceover,
    title_layout_parts,
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
        voiced_ids = {seg.id for seg in plan.segments if segment_uses_voiceover(seg)}
        speech_service = CachedVoiceService(
            result,
            project_root=project_root,
            voiced_segment_ids=voiced_ids,
        )
        self._md2video_speech_service = speech_service
        self.set_speech_service(speech_service)

        # 跨 scene 持久状态
        self.timeline = []
        self._timeline_writer = TimelineWriter(self.timeline)
        self.marker_timeline = []
        self.current_subtitles = []
        self.subtitle_heights = []
        self.is_image_active = False
        self._segment_location_by_id = {}

        # 构建 segment -> scene/shot 映射
        segment_to_scene = {}
        for scene in plan.scenes:
            for shot in scene.shots:
                for seg_id in shot.segment_ids:
                    segment_to_scene[seg_id] = scene
                    self._segment_location_by_id[seg_id] = {
                        "scene_id": scene.id,
                        "shot_id": shot.id,
                    }

        # Fallback: 如果没有 scenes（Phase 1 旧数据），用扁平循环
        if not plan.scenes:
            self._construct_flat(plan, result)
        else:
            self._construct_by_scenes(plan, result, segment_to_scene)

    def _timeline_entry(self, seg, start: float, text: str | None = None, end: float | None = None) -> dict:
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

    def _marker_entry(self, seg) -> dict:
        entry = {
            "segment_id": seg.id,
            "segment_type": seg.segment_type,
            "kind": seg.marker_data["kind"],
            "name": seg.marker_data["name"],
            "time": self.time,
        }
        entry.update(getattr(self, "_segment_location_by_id", {}).get(seg.id, {}))
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

    @staticmethod
    def _find_title_segments(plan):
        title_main = None
        title_sub = None
        for seg in plan.segments:
            if seg.segment_type == "title_main" and title_main is None:
                title_main = seg
            elif seg.segment_type == "title_sub" and title_sub is None:
                title_sub = seg
            if title_main and title_sub:
                break
        return title_main, title_sub

    def _append_timeline_entry(self, seg, start: float, text: str | None = None) -> int:
        return self._timeline_writer.append(
            self._timeline_entry(seg, start, text=text)
        )

    def _close_timeline_entry(self, timeline_index: int, end: float | None = None) -> None:
        self._timeline_writer.close(timeline_index, self.time if end is None else end)

    def _construct_flat(self, plan, result):
        """Phase 1 兼容: 扁平 segment 循环（与原逻辑完全一致）。"""
        timeline = self.timeline
        marker_timeline = self.marker_timeline
        spacing = SUBTITLE_SPACING

        # ========== 1. 标题 ==========
        title_seg, subtitle_seg = self._find_title_segments(plan)

        if title_seg or subtitle_seg:
            self._render_title(title_seg, subtitle_seg)
        self._dots_offset_tracker, self._dot1, self._dot2, self._t_tracker = \
            self._setup_dot_animation(title_seg, subtitle_seg)

        # ========== 2. 内容循环（使用提取的引用） ==========
        dots_offset_tracker = self._dots_offset_tracker
        dot1 = self._dot1
        dot2 = self._dot2

        # ========== 3. 内容循环 ==========
        current_subtitles = self.current_subtitles
        subtitle_heights = self.subtitle_heights

        for seg in iter_scene_render_segments(plan):
            stype = seg.segment_type

            # --- 小标题 ---
            if stype == "section_header":
                self._render_section_header(seg, dots_offset_tracker)
                continue

            # --- 图片标记 ---
            if stype == "marker_image" and seg.marker_data:
                marker_timeline.append(self._marker_entry(seg))
                kind = seg.marker_data["kind"]
                if kind == "start" and not self.is_image_active:
                    self.is_image_active = True
                    self.play(
                        dots_offset_tracker.animate.move_to(IMAGE_DOTS_OFFSET),
                        run_time=DOTS_TRANSITION_TIME,
                    )
                elif kind == "end" and self.is_image_active:
                    self.is_image_active = False
                    self.play(
                        dots_offset_tracker.animate.move_to(DEFAULT_DOTS_OFFSET),
                        run_time=DOTS_TRANSITION_TIME,
                    )
                continue

            # --- 音乐标记 ---
            if stype == "marker_music":
                if seg.marker_data:
                    marker_timeline.append(self._marker_entry(seg))
                continue

            # --- 正文 / 附录 ---
            if stype in ("content", "appendix"):
                line = seg.text
                wrapped_line = "\n".join(
                    [line[i:i + MAX_CHARS_PER_LINE] for i in range(0, len(line), MAX_CHARS_PER_LINE)]
                )

                start_t = self.time
                text_position = IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
                sentence = textWithFont(wrapped_line, font_size=15).move_to(text_position)
                timeline_index = self._append_timeline_entry(seg, start_t, text=line)
                if segment_uses_voiceover(seg):
                    with self._voiceover_segment(seg, line) as tracker:
                        self.add(sentence)
                    self.wait(2)
                else:
                    self.add(sentence)
                    self.wait(self._segment_duration(seg.id, default=2.0))
                self.remove(sentence)
                self._close_timeline_entry(timeline_index)

        # ========== 4. 收尾 ==========
        self._finish(dot1, dot2, self._t_tracker)

    # ========== Scene-based 渲染 ==========

    def _construct_by_scenes(self, plan, result, segment_to_scene):
        """Phase 2A: 按 scene 循环渲染。"""
        # 渲染标题
        title_main, title_sub = self._find_title_segments(plan)
        if title_main or title_sub:
            self._render_title(title_main, title_sub)
            dots_offset_tracker, dot1, dot2, t_tracker = \
                self._setup_dot_animation(title_main, title_sub)
        else:
            # 无标题时仍需初始化点动画
            dots_offset_tracker, dot1, dot2, t_tracker = self._setup_dot_animation(None, None)

        # 按 scene/shot 顺序渲染正文；标题 segment 已在标题卡片中渲染一次。
        for seg in iter_scene_render_segments(plan):
            self._render_segment(seg, dots_offset_tracker)

        self._finish(dot1, dot2, t_tracker)

    def _render_segment(self, seg, dots_offset_tracker):
        """渲染单个 segment（content/section_header/marker）。"""
        timeline = self.timeline
        marker_timeline = self.marker_timeline
        current_subtitles = self.current_subtitles
        subtitle_heights = self.subtitle_heights
        spacing = SUBTITLE_SPACING
        stype = seg.segment_type

        if stype == "section_header":
            self._render_section_header(seg, dots_offset_tracker)
            return

        if stype == "marker_image" and seg.marker_data:
            marker_timeline.append(self._marker_entry(seg))
            kind = seg.marker_data["kind"]
            if kind == "start" and not self.is_image_active:
                self.is_image_active = True
                self.play(
                    dots_offset_tracker.animate.move_to(IMAGE_DOTS_OFFSET),
                    run_time=DOTS_TRANSITION_TIME,
                )
            elif kind == "end" and self.is_image_active:
                self.is_image_active = False
                self.play(
                    dots_offset_tracker.animate.move_to(DEFAULT_DOTS_OFFSET),
                    run_time=DOTS_TRANSITION_TIME,
                )
            return

        if stype == "marker_music":
            if seg.marker_data:
                marker_timeline.append(self._marker_entry(seg))
            return

        if stype in ("content", "appendix"):
            line = seg.text
            wrapped_line = "\n".join(
                [line[i:i + MAX_CHARS_PER_LINE] for i in range(0, len(line), MAX_CHARS_PER_LINE)]
            )
            start_t = self.time
            text_position = IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
            sentence = textWithFont(wrapped_line, font_size=15).move_to(text_position)
            timeline_index = self._append_timeline_entry(seg, start_t, text=line)
            if segment_uses_voiceover(seg):
                with self._voiceover_segment(seg, line) as tracker:
                    self.add(sentence)
                self.wait(2)
            else:
                self.add(sentence)
                self.wait(self._segment_duration(seg.id, default=2.0))
            self.remove(sentence)
            self._close_timeline_entry(timeline_index)

    def _segment_duration(self, segment_id: str, default: float = 2.0) -> float:
        result = getattr(self, "_segment_result_by_id", {}).get(segment_id)
        if result:
            duration = result.end - result.start
            if duration > 0:
                return duration
        return default

    def _render_section_header(self, seg, dots_offset_tracker):
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
            with self._voiceover_segment(seg, subtitle_text):
                self.play(Write(subtitle))
                self.wait(0.5)
        else:
            self.play(Write(subtitle))
            self.wait(self._segment_duration(seg.id, default=0.5))
        timeline_index = self._append_timeline_entry(seg, start_t, text=subtitle_text)
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

    def _render_title(self, title_seg, subtitle_seg):
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
            timeline_index = self._append_timeline_entry(seg, start_t, text=seg.text)
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
        shots = self._build_shot_timeline()
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump({"text": self.timeline, "markers": self.marker_timeline, "shots": shots},
                       f, ensure_ascii=False, indent=2)
        print(f"Timeline saved: {timeline_path}")

    def _build_shot_timeline(self) -> list[dict]:
        return build_shot_timeline(self.timeline, self.marker_timeline)

    def _load_manifests(self) -> tuple[PlanManifest, ResultManifest]:
        """Load explicit PlanManifest and ExecutionAssets renderer inputs."""
        return load_manifests_from_env()
