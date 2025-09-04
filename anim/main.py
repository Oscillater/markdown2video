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

# ===========================
# Demo Scene
# ===========================
class Demo(VoiceoverScene):
    def construct(self):
        self.set_speech_service(EdgeTTSVoice())

        # ✨ 1. 在这里配置位置和动画 ✨
        # ------------------------------------
        # 文字位置
        DEFAULT_TEXT_POSITION = [0, 0, 0]
        IMAGE_TEXT_POSITION = [0.8, -0.75, 0]

        # 点动画的中心点偏移量
        DEFAULT_DOTS_OFFSET = np.array([0, 0, 0])
        IMAGE_DOTS_OFFSET = np.array([0.8, -0.75, 0]) # 移动到左上区域
        
        # 点动画切换位置时的动画时长（秒）
        DOTS_TRANSITION_TIME = 1.0
        # ------------------------------------

        data = parse_markdown_file("example.md")
        if not data:
            return

        timeline = []

        # 主标题/副标题
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

        # 将 is_image_active 初始化为场景的属性，供文字和点动画共同使用
        self.is_image_active = False

        # ✨ 2. 创建一个看不见的 "偏移量跟踪器" ✨
        # 它的位置代表了点动画的当前中心点偏移量
        dots_offset_tracker = Dot(point=DEFAULT_DOTS_OFFSET, stroke_opacity=0, fill_opacity=0)
        
        # 初始点动画
        A, B = 0.75, 0.5
        dot1, dot2 = Dot(radius=0.04, color=WHITE), Dot(radius=0.04, color=BLUE)

        # ✨ 3. 修改 Updater 函数，让它读取跟踪器的实时位置 ✨
        dot1.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([A*np.sin(1.4*t_tracker.get_value()-PI/8),
                                                         B*np.sin(2.1*t_tracker.get_value()), 0])
        ))
        dot2.add_updater(lambda m: m.move_to(
            dots_offset_tracker.get_center() + np.array([A*np.sin(1.61*t_tracker.get_value()+PI/8),
                                                         B*np.sin(1.19*t_tracker.get_value()), 0])
        ))
        self.add(dot1, dot2)

        t_tracker = ValueTracker(0)
        t_tracker.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(t_tracker)

        # 显示字幕与正文
        contents_data = data["contents"]
        subtitle_start_y = 1
        subtitle_offset_y = -0.5
        max_visible_subtitles = 4
        current_subtitles = []

        for content in contents_data:
            # h3 小标题
            if "h3" in content:
                # ... h3 逻辑保持不变 ...
                subtitle_text = content["h3"]
                start_t = self.time
                with self.voiceover(text=subtitle_text):
                    subtitle = Text(subtitle_text, font_size=20).move_to([0, 0, 0])
                    self.play(Write(subtitle))
                    self.wait(0.5)
                timeline.append({"text": subtitle_text, "start": start_t, "end": None})
                target = [-1.75, subtitle_start_y + len(current_subtitles)*subtitle_offset_y, 0]
                self.play(subtitle.animate.move_to(target).scale(0.7), run_time=1)
                current_subtitles.append(subtitle)
                if len(current_subtitles) > max_visible_subtitles:
                    rem = current_subtitles.pop(0)
                    self.play(FadeOut(rem))
                    for item in timeline:
                        if item.get("text") == rem.text and item.get("end") is None:
                            item["end"] = self.time
                            break
                    animations = []
                    for s_idx, s in enumerate(current_subtitles):
                        new_target_y = subtitle_start_y + s_idx * subtitle_offset_y
                        animations.append(s.animate.move_to([-1.75, new_target_y, 0]))
                    if animations:
                        self.play(*animations, run_time=0.5)

            # 正文文本（播放语音）
            for paragraph in content["text"]:
                for line in paragraph:
                    # ✨ 4. 根据图片标记，播放动画来平滑移动点动画的中心点 ✨
                    image_marker = _parse_image_marker(line)
                    if image_marker:
                        kind = image_marker[0]
                        if kind == 'start' and not self.is_image_active:
                            self.is_image_active = True
                            # 播放动画，让偏移量跟踪器平滑移动到新位置
                            self.play(dots_offset_tracker.animate.move_to(IMAGE_DOTS_OFFSET), run_time=DOTS_TRANSITION_TIME)
                        elif kind == 'end' and self.is_image_active:
                            self.is_image_active = False
                            # 播放动画，让偏移量跟踪器平滑移回原位
                            self.play(dots_offset_tracker.animate.move_to(DEFAULT_DOTS_OFFSET), run_time=DOTS_TRANSITION_TIME)
                        continue 

                    if _parse_music_marker(line):
                        continue
                    
                    start_t = self.time
                    with self.voiceover(text=line) as tracker:
                        # 文字的位置切换仍然是瞬间完成的
                        text_position = IMAGE_TEXT_POSITION if self.is_image_active else DEFAULT_TEXT_POSITION
                        
                        sentence = Text(line, font_size=15).move_to(text_position)
                        self.add(sentence)
                        timeline.append({"text": line, "start": start_t, "end": None})

                        self.wait(2)
                        self.remove(sentence)

                        for item in timeline:
                            if item.get("text") == line and item.get("end") is None:
                                item["end"] = self.time
                                break

        # 收尾
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

        # 自动后处理
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
                    cmd = [sys.executable, str(tool), "-v", str(video_path), "-t", str(timeline_file), "-m", str(markdown_file), "-o", str(out_path)]
                    print(f"Calling media inserter: {' '.join(cmd)}")
                    try:
                        subprocess.run(cmd, check=True)
                        print(f"✅ Media insertion finished, output: {out_path}")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Media inserter failed: {e}")
                else:
                    print("No suitable .mp4 (Demo.mp4 or other) found to post-process — skipping media insertion.")
            else:
                print(f"Media inserter script not found at {tool} — skipping.")
        except Exception as e:
            print(f"❌ An error occurred while running media insertion: {e}")