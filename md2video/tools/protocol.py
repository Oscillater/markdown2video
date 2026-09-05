"""Tool Protocol — 统一工具接口定义。
Tool 只定义 JSON 输入/输出契约，不绑定执行方式（进程内/CLI/HTTP）。
"""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """工具协议：所有工具必须实现 tool_type、provider_name 和 execute()。"""

    @property
    def tool_type(self) -> str:
        """工具类别: 'tts' | 'image' | 'video' | 'render'。"""
        ...

    @property
    def provider_name(self) -> str:
        """Provider 标识: 'edge-tts' | 'manim' | 'pexels' | ...。"""
        ...

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具，接收结构化 dict 输入，返回结构化 dict 输出。

        Visual tool (tool_type='image'/'video') 输入契约::

            {
                "scene": {"id": str, "visual_type": str, "visual_params": dict,
                          "layout_type": str, "layout_params": dict,
                          "section_context": str},
                "shot":  {"id": str, "segment_ids": list[str], "cues": list[dict]},
                "segments": [{"id": str, "text": str, "segment_type": str,
                              "audio": {"path": str, "duration": float} | None}],
                "output_dir": str,
                "base_dir": str | None,  # optional, for resolving local relative paths
            }

        Visual tool 输出契约::

            {
                "visuals": [{"shot_id": str, "path": str, "width": int,
                             "height": int, "source": str, "duration": float}]
            }

        duration 合同：会占用时间轴的素材由素材工具 probe 上报时长
        （静态图片为 0），管线原样写进 execution-assets 的 VisualAsset。

        TTS tool (tool_type='tts') 输入契约::

            {"text": str, "voice": str, "speed": float, "format": str}

        TTS tool 输出契约::

            {"path": str, "duration": float, "provider": str, "cache_key": str}

        Render tool (tool_type='render') 输入契约::

            {
                "plan_path": str,
                "execution_assets_path": str,
                "timeline_path": str,
                "output_dir": str,
                "timeout": int,
            }

        Render tool 输出契约::

            {
                "video_path": str,
                "timeline_path": str,
                "provider": str,
                "render_dir": str,
                "warnings": list[str],  # optional, timeline gate warnings
            }
        """
        ...
