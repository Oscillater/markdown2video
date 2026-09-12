"""math_canvas@1.0.0 场景画布组件注册模块（A8.1 试点，mount="scene"）。

开发期显式加载（A5 模式）::

    MD2VIDEO_COMPONENTS=md2video.components.sources.math_canvas.register

正式入库走验收入口（staged 安装 → 双跑逐帧一致 + 黄金帧 → 全过才安装）::

    python -m md2video.check_component md2video.components.sources.math_canvas.register

按场挂载（mount="scene"）：组件拿整场镜头时间线（scene_shots）+ 自己排第
几（scene_shot_index），画面状态跨 shot 累积——第 N 次访问的画布包含前
N-1 次访问画下的全部图层。

注意：本目录的 .tsx 按「安装后的位置」书写 import（`../../types` 指向
Remotion 工程 `src/registered/types.ts`）；这里只是候选源，不被 Python 执行。
"""
from pathlib import Path

from md2video.components.registry import register_component

register_component(
    "math_canvas",
    "1.0.0",
    "body",
    Path(__file__).parent / "math_canvas.tsx",
    mount="scene",
)
