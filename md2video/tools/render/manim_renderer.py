"""
ManifestDrivenScene - 基于 PlanManifest + ResultManifest 的 Manim 场景。

用法 (在 anim/ 目录下运行):
    manim -pql manim_renderer.py ManifestDrivenScene -- --plan ../artifacts/plan.json --result ../artifacts/result.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from md2video.manifest.schema import PlanManifest, ResultManifest
from md2video.tools.render.cached_voice import CachedVoiceService
from md2video.parser.md_parser import _parse_music_marker, _parse_image_marker
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
        # 从命令行参数加载 manifest
        plan, result = self._load_manifests()

        # 设置语音服务为 CachedVoiceService
        project_root = Path.cwd().parent  # anim/ -> project root
        # 收集实际会调用 voiceover 的 segment ID（排除 title_main/title_sub/marker）
        voiced_ids = {
            seg.id for seg in plan.segments
            if seg.audio_request is not None
            and seg.segment_type not in ("title_main", "title_sub", "marker_music", "marker_image")
        }
        self.set_speech_service(CachedVoiceService(result, project_root=project_root,
                                                    voiced_segment_ids=voiced_ids))

        timeline = []
        spacing = SUBTITLE_SPACING

        # ========== 1. 标题 ==========
        title_seg = None
        subtitle_seg = None
        for seg in plan.segments:
            if seg.segment_type == "title_main":
                title_seg = seg
            elif seg.segment_type == "title_sub":
                subtitle_seg = seg
            if title_seg and subtitle_seg:
                break

        main_title = textWithFont(title_seg.text, font_size=40).move_to([0, 1, 0])
        sub_title = textWithFont(subtitle_seg.text, font_size=30).move_to([0, -1, 0])
        start_t = self.time
        self.play(Write(main_title), Write(sub_title))
        timeline.append({"text": title_seg.text, "start": start_t, "end": None})
        timeline.append({"text": subtitle_seg.text, "start": start_t, "end": None})
        self.wait(1)

        # ========== 2. 时间跟踪器 + 点动画 ==========
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

        # 变点
        self.play(
            Transform(main_title, dot1),
            Transform(sub_title, dot2),
            run_time=2
        )
        timeline[-2]["end"] = self.time
        timeline[-1]["end"] = self.time
        self.remove(main_title, sub_title)
        self.add(dot1, dot2)

        # ========== 3. 内容循环 ==========
        self.is_image_active = False
        current_subtitles = []
        subtitle_heights = []

        content_segments = [s for s in plan.segments
                            if s.segment_type not in ("title_main", "title_sub")]

        for seg in content_segments:
            stype = seg.segment_type

            # --- 小标题 ---
            if stype == "section_header":
                subtitle_text = seg.text
                start_t = self.time
                with self.voiceover(text=subtitle_text):
                    subtitle = textWithFont(subtitle_text, font_size=20).move_to(DEFAULT_TEXT_POSITION)
                    if subtitle.width > SUBTITLE_MAX_WIDTH:
                        subtitle.scale(SUBTITLE_MAX_WIDTH / subtitle.width)
                    self.play(Write(subtitle))
                    self.wait(0.5)
                timeline.append({"text": subtitle_text, "start": start_t, "end": None})

                # 换行小标题
                if len(subtitle_text) > 5:
                    wrapped_text = "\n".join(
                        [subtitle_text[i:i + 5] for i in range(0, len(subtitle_text), 5)]
                    )
                    wrapped_subtitle = textWithFont(wrapped_text, font_size=12, line_spacing=0.5)
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
                    for item in timeline:
                        if item.get("text") == rem.text and item.get("end") is None:
                            item["end"] = self.time
                            break
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
                continue

            # --- 图片标记 ---
            if stype == "marker_image" and seg.marker_data:
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
                continue

            # --- 正文 / 附录 ---
            if stype in ("content", "appendix"):
                line = seg.text
                wrapped_line = "\n".join(
                    [line[i:i + MAX_CHARS_PER_LINE] for i in range(0, len(line), MAX_CHARS_PER_LINE)]
                )

                start_t = self.time
                with self.voiceover(text=line) as tracker:
                    text_position = IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
                    sentence = textWithFont(wrapped_line, font_size=15).move_to(text_position)
                    self.add(sentence)
                    timeline.append({"text": line, "start": start_t, "end": None})
                    self.wait(2)
                    self.remove(sentence)
                    for item in timeline:
                        if item.get("text") == line and item.get("end") is None:
                            item["end"] = self.time
                            break

        # ========== 4. 收尾 ==========
        if current_subtitles:
            self.play(*[FadeOut(s) for s in current_subtitles])
            for s in current_subtitles:
                for item in timeline:
                    if item.get("text") == s.text and item.get("end") is None:
                        item["end"] = self.time
                        break

        self.play(FadeOut(dot1), FadeOut(dot2))
        t_tracker.clear_updaters()

        # ========== 5. 附录 (已在上面 content_segments 循环中处理) ==========

        # ========== 6. 保存 timeline ==========
        timeline_path = Path("timeline.json")
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        print(f"Timeline saved: {timeline_path}")

    def _load_manifests(self) -> tuple[PlanManifest, ResultManifest]:
        """从 artifacts/ 目录加载 PlanManifest 和 ResultManifest。"""
        # 从 anim/ 目录运行，manifests 在上级 artifacts/ 目录
        candidates = [
            Path.cwd().parent / "artifacts",  # anim/ -> project/artifacts/
            Path.cwd() / "artifacts",          # 直接在 cwd/artifacts/
        ]
        artifacts_dir = None
        for d in candidates:
            if d.exists():
                artifacts_dir = d
                break
        if artifacts_dir is None:
            raise FileNotFoundError("artifacts/ directory not found")

        plan_path = artifacts_dir / "plan.json"
        result_path = artifacts_dir / "result.json"

        plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
        result = ResultManifest.model_validate_json(result_path.read_text(encoding="utf-8"))
        return plan, result
