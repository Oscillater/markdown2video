from manim import *
import numpy as np
import random

class LeftRightDemo(Scene):
    def construct(self):

        # ======== 题目显示 ========
        # 大标题
        main_title = Text("普通玩家001", font_size=40)  # 替换为实际大标题
        main_title.move_to([0, 1, 0])  # 显示在屏幕上方

        # 小标题
        sub_title = Text("小标题示例", font_size=30)  # 替换为实际小标题
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

        # ======== 小标题 + 正文（右侧）========
        subtitle = Text("标题", font_size=20)
        subtitle.move_to([1.25, 0, 0])  

        self.play(Write(subtitle))
        self.wait(0.5)

        # 小标题移动到底部左侧
        subtitle_target = subtitle.copy().scale(0.5)
        subtitle_target.move_to([-1.75, 1, 0])
        self.play(Transform(subtitle, subtitle_target))
        self.wait(0.5)

        # 正文内容依次显示
        contents = [
            "在古老的世界尽头，虚空沉眠。",
            "传说中有一本书，载录诸神的低语。",
            "唯有真实者，能窥其中奥秘。",
            "每翻一页，世界便多一分裂。",
            "你，准备好面对它了吗？"
        ]

        for line in contents:
            sentence = Text(line, font_size=15).move_to([0, 0, 0])  # 右中位置
            self.play(Write(sentence), run_time=2)
            self.wait(1)
            self.play(FadeOut(sentence), run_time=1)

        self.wait(1)

       

        # 淡出所有旧内容
        self.play(
            FadeOut(dot1),
            FadeOut(dot2),
            FadeOut(subtitle),
        )
         # （可选）移除 updater（场景结束前）
        dot1.remove_updater(update_dot1)
        dot2.remove_updater(update_dot2)
        t_tracker.remove_updater(advance_tracker)

        # ======== 附录显示 ========
        appendix = [
            "附录内容第一句。",
            "附录内容第二句。",
            "附录内容第三句。"
        ]

        for line in appendix:
            appendix_text = Text(line, font_size=15).move_to([0, 0, 0])  # 底部显示
            self.play(Write(appendix_text), run_time=2)
            self.wait(1)
            self.play(FadeOut(appendix_text), run_time=1)

        self.wait(1)