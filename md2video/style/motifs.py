"""母题（motif）kind 注册表：pack 按名字引用，引擎提供实现。

母题是能力原语：几何/频率等引擎空间常量住在本模块的实现类里，不属于
pack 数据；pack 只声明 kind 名与颜色/时长 token。新母题 = 新实现类 +
@register_motif 注册，包零代码。
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
from manim import Dot, FadeOut, PI, Transform, ValueTracker

_MOTIF_KINDS: dict[str, Callable[..., Any]] = {}


def register_motif(kind: str) -> Callable[[type], type]:
    """把母题实现类注册到 kind 名下；重复注册 fail fast。"""

    def decorator(cls: type) -> type:
        if kind in _MOTIF_KINDS:
            raise ValueError(f"Motif kind already registered: {kind}")
        cls.kind = kind
        _MOTIF_KINDS[kind] = cls
        return cls

    return decorator


def motif_kinds() -> list[str]:
    return sorted(_MOTIF_KINDS)


def create_motif(
    kind: str,
    primary_color: str,
    secondary_color: str,
    transition_duration: float,
    warnings_sink: list[str] | None = None,
) -> Any | None:
    """按 kind 实例化母题；引擎不认识的 kind 优雅降级为 None + warning。"""
    cls = _MOTIF_KINDS.get(kind)
    if cls is None:
        warning = (
            f"Unknown motif kind {kind!r}; skipping motif "
            f"(pack/engine capability mismatch)"
        )
        if warnings_sink is not None:
            warnings_sink.append(warning)
        print(f"  Style warning: {warning}")
        return None
    return cls(
        primary_color=primary_color,
        secondary_color=secondary_color,
        transition_duration=transition_duration,
    )


@register_motif("orbit_dots")
class OrbitDotsMotif:
    """orbit_dots 母题：双圆点绕隐形锚点轨道运动（自 manim_renderer 搬家）。

    引擎空间常量（锚点、半径、轨道振幅/频率、交接时长）是能力原语，
    不是 pack 数据。
    """

    _DEFAULT_ANCHOR = np.array([0.2, 0.0, 0.0])   # 原 config.DEFAULT_DOTS_OFFSET
    _IMAGE_ANCHOR = np.array([-0.5, 0.0, 0.0])    # 原 config.IMAGE_DOTS_OFFSET
    _DOT_RADIUS = 0.04
    _ORBIT_A = 0.75
    _ORBIT_B = 0.5
    _HANDOFF_RUN_TIME = 2.0

    def __init__(self, primary_color: str, secondary_color: str,
                 transition_duration: float):
        self._primary_color = primary_color
        self._secondary_color = secondary_color
        self._transition_duration = transition_duration
        self._t_tracker: ValueTracker | None = None
        self._anchor_tracker: Dot | None = None
        self._dots: list[Dot] = []

    @property
    def dots(self) -> tuple[Dot, ...]:
        return tuple(self._dots)

    def setup(self, scene: Any) -> None:
        """创建轨道时钟、隐形锚点与双圆点（只加入场景，不播放动画）。"""
        t_tracker = ValueTracker(0)
        t_tracker.add_updater(lambda m, dt: m.increment_value(dt))
        scene.add(t_tracker)
        self._t_tracker = t_tracker

        anchor_tracker = Dot(
            point=self._DEFAULT_ANCHOR, stroke_opacity=0, fill_opacity=0,
        )
        scene.add(anchor_tracker)
        self._anchor_tracker = anchor_tracker

        A, B = self._ORBIT_A, self._ORBIT_B
        dot1 = Dot(radius=self._DOT_RADIUS, color=self._primary_color)
        dot2 = Dot(radius=self._DOT_RADIUS, color=self._secondary_color)
        dot1.add_updater(lambda m: m.move_to(
            anchor_tracker.get_center() + np.array([
                A * np.sin(1.4 * t_tracker.get_value() - PI / 8),
                B * np.sin(2.1 * t_tracker.get_value()), 0
            ])
        ))
        dot2.add_updater(lambda m: m.move_to(
            anchor_tracker.get_center() + np.array([
                A * np.sin(1.61 * t_tracker.get_value() + PI / 8),
                B * np.sin(1.19 * t_tracker.get_value()), 0
            ])
        ))
        self._dots = [dot1, dot2]

    def play_title_handoff(self, scene: Any, pairs: list[tuple[Any, int]]) -> None:
        """标题文字 Transform 成母题圆点并接管场景。

        pairs: [(标题 mobject, 圆点槽位)]。圆点此前不加入场景，
        交接后才 add——与原渲染器行为一致。
        """
        transforms = [
            Transform(mobject, self._dots[slot]) for mobject, slot in pairs
        ]
        scene.play(*transforms, run_time=self._HANDOFF_RUN_TIME)
        scene.remove(*[mobject for mobject, _ in pairs])
        scene.add(*self._dots)

    def dodge(self, scene: Any, target: str) -> None:
        """锚点让位动画：图片激活时挪开（'image'），结束回原位（'default'）。"""
        if target == "image":
            anchor = self._IMAGE_ANCHOR
        elif target == "default":
            anchor = self._DEFAULT_ANCHOR
        else:
            raise ValueError(f"Unknown dodge target: {target}")
        scene.play(
            self._anchor_tracker.animate.move_to(anchor),
            run_time=self._transition_duration,
        )

    def teardown(self, scene: Any) -> None:
        """收尾：淡出圆点、停掉轨道时钟。"""
        if self._dots:
            scene.play(*[FadeOut(dot) for dot in self._dots])
        if self._t_tracker is not None:
            self._t_tracker.clear_updaters()
