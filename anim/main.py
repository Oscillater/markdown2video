# demo.py
from manim import *
import numpy as np
from pathlib import Path
from md_parser import parse_markdown_file
from manim_voiceover import VoiceoverScene
import asyncio
from edge_tts import Communicate

# ===========================
# Edge TTS 服务，兼容 manim-voiceover 0.3.7
# ===========================
class EdgeTTSVoice:
    def __init__(self, voice="zh-CN-YunxiNeural"):
        self.voice = voice
        self.cache_dir = Path("voice_cache")
        self.cache_dir.mkdir(exist_ok=True)

    def _wrap_generate_from_text(self, text: str, **kwargs):
        """兼容 manim-voiceover 0.3.7 的接口"""
        audio_file = self.cache_dir / f"{hash(text)}.wav"

        async def save():
            comm = Communicate(text=text, voice=self.voice)
            await comm.save(str(audio_file))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(save())
        loop.close()

        return {"final_audio": audio_file.name, "text": text}

# ===========================
# Demo Scene
# ===========================
class Demo(VoiceoverScene):
    def construct(self):
        self.set_speech_service(EdgeTTSVoice())

        data = parse_markdown_file("example.md")
        if not data:
            return

        # 主标题
        main_title = Text(data["h1"], font_size=40).move_to([0, 1, 0])
        sub_title = Text(data["h2"], font_size=30).move_to([0, -1, 0])
        self.play(Write(main_title), Write(sub_title))
        self.wait(1)
        self.play(FadeOut(main_title), FadeOut(sub_title))

        # 初始点动画
        A, B = 0.75, 0.5
        dot1, dot2 = Dot(radius=0.04, color=WHITE), Dot(radius=0.04, color=BLUE)
        dot1.move_to([A*np.sin(-PI/8), 0, 0])
        dot2.move_to([A*np.sin(PI/8), 0, 0])
        self.add(dot1, dot2)

        t_tracker = ValueTracker(0)
        t_tracker.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(t_tracker)

        dot1.add_updater(lambda m: m.move_to([A*np.sin(1.4*t_tracker.get_value()-PI/8),
                                              B*np.sin(2.1*t_tracker.get_value()), 0]))
        dot2.add_updater(lambda m: m.move_to([A*np.sin(1.61*t_tracker.get_value()+PI/8),
                                              B*np.sin(1.19*t_tracker.get_value()), 0]))

        # 显示字幕与文本
        contents_data = data["contents"]
        subtitle_start_y = 1
        subtitle_offset_y = -0.5
        max_visible_subtitles = 4
        current_subtitles = []

        for content in contents_data:
            # h3 部分保持不变（有写入动画）
            subtitle_text = content["h3"]
            with self.voiceover(text=subtitle_text):
                subtitle = Text(subtitle_text, font_size=20).move_to([0, 0, 0])
                self.play(Write(subtitle))
                self.wait(0.5)

            target = [-1.75,
                      subtitle_start_y + len(current_subtitles)*subtitle_offset_y,
                      0]
            self.play(subtitle.animate.move_to(target).scale(0.7), run_time=1)
            current_subtitles.append(subtitle)

            if len(current_subtitles) > max_visible_subtitles:
                rem = current_subtitles.pop(0)
                self.play(FadeOut(rem))
                for s in current_subtitles:
                    dest = s.copy().move_to(s.get_center() +
                                            np.array([0, subtitle_offset_y, 0]))
                    self.play(Transform(s, dest), run_time=0.5)

            # 正文文本部分：直接显现，显示时间等于语音时长，直接消失
            for paragraph in content["text"]:
                for line in paragraph:
                    with self.voiceover(text=line) as tracker:
                        sentence = Text(line, font_size=15).move_to([0, 0, 0])
                        self.add(sentence)                # 直接显现
                        self.wait(tracker.duration)       # 保持语音时长
                        self.remove(sentence)             # 直接消失

        # 收尾淡出
        for s in current_subtitles:
            self.play(FadeOut(s))
        self.play(FadeOut(dot1), FadeOut(dot2))
        t_tracker.clear_updaters()

        # 附录文本：同样直接显现 → 保持 → 消失
        for line in data.get("appendix", []):
            txt = Text(line, font_size=15).move_to([0, 0, 0])
            self.add(txt)
            self.wait(tracker.duration)
            self.remove(txt)
