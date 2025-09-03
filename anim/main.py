from manim import *
import numpy as np
from pathlib import Path
from md_parser import parse_markdown_file,_parse_music_marker
from manim_voiceover import VoiceoverScene
import asyncio
from edge_tts import Communicate
import json
import subprocess
import sys

# ===========================
# Edge TTS 服务，兼容 manim-voiceover 0.3.7
# ===========================
class EdgeTTSVoice:
    def __init__(self, voice="zh-CN-YunxiNeural"):
        self.voice = voice
        self.cache_dir = Path("voice_cache")
        self.cache_dir.mkdir(exist_ok=True)

    def _wrap_generate_from_text(self, text: str, **kwargs):
        """兼容 manim-voiceover 的接口：同步保存到缓存文件并返回文件名"""
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

        # 记录文字显示/消失时间
        timeline = []

        # 主标题/副标题（不播放语音）
        main_title = Text(data["h1"], font_size=40).move_to([0, 1, 0])
        sub_title = Text(data["h2"], font_size=30).move_to([0, -1, 0])
        start_t = self.time
        self.play(Write(main_title), Write(sub_title))
        timeline.append({"text": data["h1"], "start": start_t, "end": None})
        timeline.append({"text": data["h2"], "start": start_t, "end": None})

        self.wait(1)
        self.play(FadeOut(main_title), FadeOut(sub_title))
        timeline[-2]["end"] = self.time
        timeline[-1]["end"] = self.time

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

        # 显示字幕与正文
        contents_data = data["contents"]
        subtitle_start_y = 1
        subtitle_offset_y = -0.5
        max_visible_subtitles = 4
        current_subtitles = []

        for content in contents_data:
            # h3 小标题（播放语音）
            subtitle_text = content["h3"]
            start_t = self.time
            with self.voiceover(text=subtitle_text):
                subtitle = Text(subtitle_text, font_size=20).move_to([0, 0, 0])
                self.play(Write(subtitle))
                self.wait(0.5)
            timeline.append({"text": subtitle_text, "start": start_t, "end": None})

            # 移动字幕位置
            target = [-1.75,
                      subtitle_start_y + len(current_subtitles)*subtitle_offset_y,
                      0]
            self.play(subtitle.animate.move_to(target).scale(0.7), run_time=1)
            current_subtitles.append(subtitle)

            if len(current_subtitles) > max_visible_subtitles:
                rem = current_subtitles.pop(0)
                self.play(FadeOut(rem))
                # 设置被移除字幕的结束时间
                for item in timeline:
                    if item.get("text") == rem.text and item.get("end") is None:
                        item["end"] = self.time
                        break

                for s in current_subtitles:
                    dest = s.copy().move_to(s.get_center() +
                                            np.array([0, subtitle_offset_y, 0]))
                    self.play(Transform(s, dest), run_time=0.5)

            # 正文文本（播放语音）
            for paragraph in content["text"]:
                for line in paragraph:
                    # 如果是音乐标记，跳过（不合成语音/不是音乐标记，跳过（不合成语音/不显示字幕/不写入 timeline）
                    if _parse_music_marker(line):
                        continue

                    start_t = self.time
                    with self.voiceover(text=line) as tracker:
                        sentence = Text(line, font_size=15).move_to([0, 0, 0])
                        self.add(sentence)
                    timeline.append({"text": line, "start": start_t, "end": None})

                    self.wait(2)  # 动画显示时间为准
                    self.remove(sentence)

                    for item in timeline:
                        if item.get("text") == line and item.get("end") is None:
                            item["end"] = self.time
                            break

        # 收尾淡出字幕
        for s in current_subtitles:
            self.play(FadeOut(s))
            for item in timeline:
                if item.get("text") == s.text and item.get("end") is None:
                    item["end"] = self.time
                    break

        self.play(FadeOut(dot1), FadeOut(dot2))
        t_tracker.clear_updaters()

        # 附录文本（不播放语音）
        for line in data.get("appendix", []):
            # 跳过附录中的音乐标记
            if _parse_music_marker(line):
                continue

            start_t = self.time
            txt = Text(line, font_size=15).move_to([0, 0, 0])
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

        # 自动后处理：调用工具脚本把音乐合并到渲染后的视频（寻找最近生成的 .mp4 作为输入）
        try:
            tool = Path("insert_music.py")
            if tool.exists():
                # 优先查找名为 Demo.mp4 的文件（递归），找不到再回退到查找最近修改的 .mp4
                demo_candidates = list(Path.cwd().rglob("Demo.mp4"))
                if demo_candidates:
                    video_path = max(demo_candidates, key=lambda p: p.stat().st_mtime)
                else:
                    mp4s = [p for p in Path.cwd().rglob("*.mp4") if "render_with_music" not in str(p)]
                    video_path = max(mp4s, key=lambda p: p.stat().st_mtime) if mp4s else None

                if video_path:
                    out_path = Path.cwd() / "render_with_music.mp4"
                    cmd = [
                        sys.executable, str(tool),
                        "-v", str(video_path),
                        "-t", str(Path.cwd() / "timeline.json"),
                        "-m", str(Path.cwd() / "example.md"),
                        "-o", str(out_path)
                    ]
                    print("Calling music inserter:", " ".join(cmd))
                    try:
                        subprocess.run(cmd, check=True)
                        print("Music insertion finished, output:", out_path)
                    except subprocess.CalledProcessError as e:
                        print("Music inserter failed:", e)
                else:
                    print("No suitable .mp4 (Demo.mp4 or other) found to post-process — skip music insertion.")
            else:
                print("Music inserter script not found at tools/insert_music_from_parser.py — skip.")
        except Exception as e:
            print("Error while running music insertion:", e)