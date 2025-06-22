from manim import *
import numpy as np  # 确保导入 NumPy

class Demo(Scene):
    def construct(self):
        # 显示文字
        text = Text("御虚记", gradient=(BLUE_C, BLUE_D), font_size=20)
        self.play(Write(text))
        self.wait()

        # 设置参数
        A, B = 0.375, 0.25
        total_time = 5  # 秒
        steps = 150  # 减少步数以加快速度
        dt = total_time / steps

        # 点1（蓝色）
        dot1 = Dot(radius=0.02, color=WHITE)

        # 点2（白色）
        dot2 = Dot(radius=0.02, color=BLUE)

        # 设置初始位置
        x1_start = A * np.sin(-PI / 8)
        y1_start = B * np.sin(0)
        x2_start = A * np.sin(PI / 8)
        y2_start = B * np.sin(0)
        dot1.move_to([x1_start, y1_start, 0])
        dot2.move_to([x2_start, y2_start, 0])

        # 文字变为两个点
        self.play(Transform(text, VGroup(dot1, dot2)))
        self.remove(text)
        self.add(dot1, dot2)
        self.wait(0.5)

        # 平移到左上角
        shift_vector = np.array([-1.75, 1, 0])  # 转换为 NumPy 数组
        self.play(dot1.animate.shift(shift_vector), dot2.animate.shift(shift_vector))
        self.wait(0.5)

        for i in range(steps):
            t = i * dt

            # 蓝点路径（李萨如）
            x1 = A * np.sin(2 * t - PI / 8)
            y1 = B * np.sin(3 * t)
            dot1.move_to(np.array([x1, y1, 0]) + shift_vector)  # 使用 NumPy 数组相加

            # 白点路径（不同频率，相位错位）
            x2 = A * np.sin(2.3 * t - PI / 8)
            y2 =B * np.sin(1.7 * t)
            dot2.move_to(np.array([x2, y2, 0]) + shift_vector)  # 使用 NumPy 数组相加

            self.wait(1 / 30)