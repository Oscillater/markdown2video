from manim import *
import numpy as np
from pathlib import Path
from md_parser import parse_markdown_file, _parse_music_marker, _parse_image_marker
from manim_voiceover import VoiceoverScene
import asyncio
from edge_tts import Communicate
import json
import subprocess
import sys

# ===========================
# Edge TTS 服务
# ===========================
class EdgeTTSVoice:
    def __init__(self, voice="zh-CN-YunxiNeural"):
        self.voice = voice
        self.cache_dir = Path("voice_cache")
        self.cache_dir.mkdir(exist_ok=True)

    def _wrap_generate_from_text(self, text: str, **kwargs):
        audio_file = self.cache_dir / f"{hash(text)}.wav"

        async def save():
            comm = Communicate(text=text, voice=self.voice)
            await comm.save(str(audio_file))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(save())
        loop.close()

        return {"final_audio": audio_file.name, "text": text}

def textWithFont(text, font="FZShuSong-Z01S", **kwargs):
    return Text(text, font=font, **kwargs)

# ===========================
# Demo Scene
# ===========================
class Demo(VoiceoverScene):
    def construct(self):
        self.set_speech_service(EdgeTTSVoice())

        # ✨ 配置位置和动画 ✨
        RIGHT_X = 0.2
        DEFAULT_TEXT_POSITION = [RIGHT_X, 0, 0]
        IMAGE_TEXT_POSITION = [0.8, -0.75, 0]
        LEFT_X = -1.75
        
        DOTS_TRANSITION_TIME = 1.0
        MAX_CHARS_PER_LINE = 10
        spacing = 0.1
        subtitle_start_y = 1.0
        screen_bottom = -1.0

        data = parse_markdown_file("example.md")
        if not data:
            return

        timeline = []

        # 创建标题
        main_title = textWithFont(data["h1"], font_size=40).move_to([0, 1, 0])
        sub_title = textWithFont(data["h2"], font_size=30).move_to([0, -1, 0])
        start_t = self.time
        self.play(Write(main_title), Write(sub_title))
        timeline.append({"text": data["h1"], "start": start_t, "end": None})
        timeline.append({"text": data["h2"], "start": start_t, "end": None})
        self.wait(1)

        # 时间跟踪器
        t_tracker = ValueTracker(0)
        t_tracker.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(t_tracker)

        # 点动画
        dots_offset_tracker = Dot(point=np.array([RIGHT_X, 0, 0]), stroke_opacity=0, fill_opacity=0)
        self.add(dots_offset_tracker)
        A, B = 0.75, 0.5
        dot1 = Dot(radius=0.04, color=WHITE)
        dot2 = Dot(radius=0.04, color=BLUE)
        dot1.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([A*np.sin(1.4*t_tracker.get_value()-PI/8),
                                                        B*np.sin(2.1*t_tracker.get_value()), 0])
        ))
        dot2.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([A*np.sin(1.61*t_tracker.get_value()+PI/8),
                                                        B*np.sin(1.19*t_tracker.get_value()), 0])
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

        self.is_image_active = False
        contents_data = data["contents"]

        current_subtitles = []
        subtitle_heights = []

        # 右侧显示 y 坐标
        right_y = 0.5

        for content in contents_data:
            # --------------------
            # 小标题显示在左侧
            # --------------------
            if "h3" in content:
                subtitle_text = content["h3"]
                start_t = self.time
                with self.voiceover(text=subtitle_text):
                    subtitle = textWithFont(subtitle_text, font_size=20).move_to(DEFAULT_TEXT_POSITION)
                    RIGHT_MAX_WIDTH = 3.0  # 右侧显示区域允许的最大宽度
                    if subtitle.width > RIGHT_MAX_WIDTH:
                        subtitle.scale(RIGHT_MAX_WIDTH / subtitle.width)
                    self.play(Write(subtitle))
                    self.wait(0.5)
                timeline.append({"text": subtitle_text, "start": start_t, "end": None})

                # 换行小标题
                if len(subtitle_text) > 5:
                    wrapped_text = '\n'.join([subtitle_text[i:i+5] for i in range(0, len(subtitle_text), 5)])
                    wrapped_subtitle = textWithFont(wrapped_text, font_size=12, line_spacing=0.5)
                    self.play(FadeOut(subtitle))
                    subtitle = wrapped_subtitle

                subtitle_height = subtitle.height
                need_to_remove = False
                if current_subtitles:
                    last_subtitle = current_subtitles[-1]
                    last_bottom = last_subtitle.get_bottom()[1]
                    new_y = last_bottom - subtitle_height - spacing
                    new_bottom = new_y - subtitle_height/2
                    if new_bottom < screen_bottom:
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
                    current_y = subtitle_start_y
                    for s in current_subtitles:
                        s_height = s.height
                        animations.append(s.animate.move_to([LEFT_X, current_y, 0]))
                        current_y -= s_height + spacing
                    if animations:
                        self.play(*animations, run_time=0.5)

                if current_subtitles:
                    last_subtitle = current_subtitles[-1]
                    new_y = last_subtitle.get_bottom()[1] - subtitle.height/2 - spacing
                else:
                    new_y = subtitle_start_y

                self.play(subtitle.animate.move_to([LEFT_X, new_y, 0]), run_time=1)
                current_subtitles.append(subtitle)
                subtitle_heights.append(subtitle_height)

            # --------------------
            # 正文显示在右侧
            # --------------------
            for paragraph in content["text"]:
                for line in paragraph:
                    image_marker = _parse_image_marker(line)
                    if image_marker:
                        kind = image_marker[0]
                        if kind == 'start' and not self.is_image_active:
                            self.is_image_active = True
                            self.play(dots_offset_tracker.animate.move_to(IMAGE_DOTS_OFFSET), run_time=DOTS_TRANSITION_TIME)
                        elif kind == 'end' and self.is_image_active:
                            self.is_image_active = False
                            self.play(dots_offset_tracker.animate.move_to(DEFAULT_DOTS_OFFSET), run_time=DOTS_TRANSITION_TIME)
                        continue 

                    if _parse_music_marker(line):
                        continue

                    # ---- 新增：每 10 个字换行 ----
                    max_chars_per_line = 10
                    wrapped_line = '\n'.join([line[i:i+max_chars_per_line] for i in range(0, len(line), max_chars_per_line)])

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

        # 收尾左侧小标题
        if current_subtitles:
            self.play(*[FadeOut(s) for s in current_subtitles])
            for s in current_subtitles:
                for item in timeline:
                    if item.get("text") == s.text and item.get("end") is None:
                        item["end"] = self.time
                        break

        self.play(FadeOut(dot1), FadeOut(dot2))
        t_tracker.clear_updaters()

        # 附录文本
        for line in data.get("appendix", []):
            if _parse_music_marker(line) or _parse_image_marker(line):
                continue
            start_t = self.time
            txt = textWithFont(line, font_size=15).move_to([0, 0, 0])
            self.add(txt)
            timeline.append({"text": line, "start": start_t, "end": None})
            self.wait(2)
            self.remove(txt)
            for item in timeline:
                if item.get("text") == line and item.get("end") is None:
                    item["end"] = self.time
                    break

        # 保存时间轴
        with open("timeline.json", "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)

        # 后处理
        try:
            tool = Path("insert_media.py")
            if tool.exists():
                media_dir = Path.cwd() / "media"
                demo_candidates = list(media_dir.rglob("Demo.mp4"))
                if not demo_candidates:
                    demo_candidates = list(Path.cwd().rglob("Demo.mp4"))
                if demo_candidates:
                    video_path = max(demo_candidates, key=lambda p: p.stat().st_mtime)
                else:
                    mp4s = [p for p in media_dir.rglob("*.mp4") if "render_with_media" not in str(p)]
                    if not mp4s:
                        mp4s = [p for p in Path.cwd().rglob("*.mp4") if "render_with_media" not in str(p)]
                    video_path = max(mp4s, key=lambda p: p.stat().st_mtime) if mp4s else None
                if video_path:
                    out_path = video_path.parent / "render_with_media.mp4"
                    timeline_file = Path.cwd() / "timeline.json"
                    markdown_file = Path.cwd() / "example.md"
                    cmd = [
                        sys.executable, str(tool),
                        "-v", str(video_path),
                        "-t", str(timeline_file),
                        "-m", str(markdown_file),
                        "-o", str(out_path)
                    ]
                    print(f"Calling media inserter: {' '.join(cmd)}")
                    try:
                        subprocess.run(cmd, check=True)
                        print(f"✅ Media insertion finished, output: {out_path}")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Media inserter failed: {e}")
                else:
                    print("No suitable .mp4 found — skipping media insertion.")
            else:
                print(f"Media inserter script not found at {tool} — skipping.")
        except Exception as e:
            print(f"❌ An error occurred while running media insertion: {e}")
