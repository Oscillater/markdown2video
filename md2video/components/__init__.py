"""表现组件子系统（A8）。

表现组件 = 接管一个 scene 正文画面的 Remotion 组件：输入 = 文字 +
每段可见窗口 + 画布尺寸，输出 = 自由画面（自带视觉，不消费 pack
token）。契约与注册约定见 `md2video/components/registry.py` 与
docs/architecture.md「表现组件」。
"""
