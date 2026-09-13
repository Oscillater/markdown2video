"""step_list@1.0.0 表现组件注册模块（A8 首批第一方示例）。

开发期显式加载（A5 模式）::

    MD2VIDEO_COMPONENTS=md2video.components.sources.step_list.register

正式入库走验收入口（staged 安装 → 双跑逐帧一致 + 黄金帧 → 全过才安装）::

    python -m md2video.check_component md2video.components.sources.step_list.register

注意：本目录的 .tsx 按「安装后的位置」书写 import（`../../types` 指向
Remotion 工程 `src/registered/types.ts`）；这里只是候选源，不被 Python 执行。
"""
from pathlib import Path

from md2video.components.registry import register_component

register_component(
    "step_list",
    "1.0.2",
    "body",
    Path(__file__).parent / "step_list.tsx",
)
