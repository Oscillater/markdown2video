from manim import *
import numpy as np
import random
from md_parser import parse_markdown_file, custom_sentence_split
class Demo(Scene):
    def construct(self):
        data=parse_markdown_file("example.md")
        if not data:
            return
        # ======== 题目显示 ========
        # 大标题
        main_title = Text(data["h1"], font_size=40)  # 替换为实际大标题
        main_title.move_to([0, 1, 0])  # 显示在屏幕上方

        # 小标题
        sub_title = Text(data["h2"], font_size=30)  # 替换为实际小标题
        sub_title.move_to([0, -1, 0])  # 显示在屏幕中间

        # 同时显示大标题和小标题
        self.play(Write(main_title), Write(sub_title))
        self.wait(1)

        # 同时淡出大标题和小标题
        self.play(FadeOut(main_title), FadeOut(sub_title))

        # ======== 初始标题 “御虚记” ==========
        title_text = Text("御虚记", gradient=(BLUE_C, BLUE_D), font_size=20)
        self.play(Write(title_text))
        self.wait()

        # ======== 点动画参数 ========
        A, B = 0.75, 0.5

        # 创建两个点
        dot1 = Dot(radius=0.04, color=WHITE)
        dot2 = Dot(radius=0.04, color=BLUE)

        # 设置初始位置
        x1_start = A * np.sin(-PI / 8)
        y1_start = B * np.sin(0)
        x2_start = A * np.sin(PI / 8)
        y2_start = B * np.sin(0)
        dot1.move_to([x1_start, y1_start, 0])
        dot2.move_to([x2_start, y2_start, 0])

        # 文字变为两个点
        self.play(Transform(title_text, VGroup(dot1, dot2)))
        self.remove(title_text)
        self.add(dot1, dot2)
        # 在 self.wait(1) 的时间内缓缓降低点的透明度
        self.play(
            AnimationGroup(
                dot1.animate.set_opacity(0.75),
                dot2.animate.set_opacity(0.75),
                lag_ratio=0
            ),
            run_time=1
        )

        # ======== 时间推进器 + 点 Updater（永不停止）========
        t_tracker = ValueTracker(0)

        def advance_tracker(mob, dt):
            mob.increment_value(dt)

        t_tracker.add_updater(advance_tracker)
        self.add(t_tracker)

        def update_dot1(dot):
            t = t_tracker.get_value()
            x1 = A * np.sin(1.4 * t - PI / 8)
            y1 = B * np.sin(2.1 * t)
            dot.move_to(np.array([x1, y1, 0]) )

        def update_dot2(dot):
            t = t_tracker.get_value()
            x2 = A * np.sin(1.61 * t + PI / 8)
            y2 = B * np.sin(1.19 * t)
            dot.move_to(np.array([x2, y2, 0]) )

        dot1.add_updater(update_dot1)
        dot2.add_updater(update_dot2)
        self.add(dot1, dot2)

        # ======== 小标题 + 正文（左侧排列 + 动态移动 + 缩小）========
        contents_data = data["contents"]  # 从解析结果中获取内容

        # 初始位置和偏移量
        subtitle_start_y = 1  # 左侧标题初始 y 坐标
        subtitle_offset_y = -0.5  # 每个标题的垂直间距
        max_visible_subtitles = 4  # 左侧最多显示的标题数量

        # 存储当前显示的标题对象
        current_subtitles = []

        for content in contents_data:
            # 创建小标题并在屏幕正中显示
            subtitle_text = content["h3"]
            subtitle = Text(subtitle_text, font_size=20)
            subtitle.move_to([0, 0, 0])  # 屏幕正中
            self.play(Write(subtitle))
            self.wait(0.5)

            # 移动小标题到左侧排列并缩小到 0.7 倍
            target_position = [-1.75, subtitle_start_y + len(current_subtitles) * subtitle_offset_y, 0]
            self.play(subtitle.animate.move_to(target_position).scale(0.7), run_time=1)
            current_subtitles.append(subtitle)

            # 如果标题数量超过屏幕范围，移出画面的标题消失
            if len(current_subtitles) > max_visible_subtitles:
                removed_subtitle = current_subtitles.pop(0)
                self.play(FadeOut(removed_subtitle))

                # 将剩余标题整体上移
                for s in current_subtitles:
                    s_target = s.copy().move_to(s.get_center() + np.array([0, subtitle_offset_y, 0]))
                    self.play(Transform(s, s_target), run_time=0.5)

            self.wait(0.5)

            # 显示对应的正文内容
            for paragraph in content["text"]:
                for line in paragraph:
                    sentence = Text(line, font_size=15).move_to([0, 0, 0])  # 屏幕中间
                    self.play(Write(sentence), run_time=2)
                    self.wait(1)
                    self.play(FadeOut(sentence), run_time=1)

            self.wait(1)

        # 淡出所有剩余的小标题
        for subtitle in current_subtitles:
            self.play(FadeOut(subtitle))
        # 淡出所有旧内容
        self.play(
            FadeOut(dot1),
            FadeOut(dot2),
        )
         # （可选）移除 updater（场景结束前）
        dot1.remove_updater(update_dot1)
        dot2.remove_updater(update_dot2)
        t_tracker.remove_updater(advance_tracker)

        # ======== 附录显示 ========
        appendix = data["appendix"]
        for line in appendix:
            appendix_text = Text(line, font_size=15).move_to([0, 0, 0])  # 底部显示
            self.play(Write(appendix_text), run_time=2)
            self.wait(1)
            self.play(FadeOut(appendix_text), run_time=1)

        self.wait(1)