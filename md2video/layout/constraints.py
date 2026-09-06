"""Layout 约束注册表与结构化裁决（A5）。

「提案→裁判→交付」里的裁判层：内置规则与外部规则走同一通道（零特权
注册 API），对候选 region 集合做属性校验——安全区包含、内容区不重叠、
最小尺寸——并一次报出全部 `LayoutIssue`（code + region + 期望/实际数值
+ 修改建议）。

外部约束模块通过 env `MD2VIDEO_LAYOUT_CONSTRAINTS`（逗号分隔的 Python
模块路径）显式加载：pipeline 启动时导入并执行其 `register_constraint`
注册，导入失败 fail fast。设计包 JSON 永远是纯数据、绝不被执行；要自
定义规则的包作者随包附一段独立注册模块，由用户显式启用。
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Callable, List

from md2video.layout.schema import ComputedLayout, LayoutBox

LAYOUT_CONSTRAINTS_ENV = "MD2VIDEO_LAYOUT_CONSTRAINTS"

# 最小 region 尺寸（归一化）：小于它的 region 装不下任何可读内容
MIN_REGION_WIDTH = 0.05
MIN_REGION_HEIGHT = 0.05


@dataclass(frozen=True)
class LayoutGeometry:
    """待裁决的候选 region 集合（提案与模板产出的共同形状）。"""

    frame_width: int
    frame_height: int
    safe_area: LayoutBox
    regions: dict[str, LayoutBox]
    safe_region_names: tuple[str, ...]
    content_region_names: tuple[str, ...]


@dataclass(frozen=True)
class LayoutIssue:
    """一条结构化 layout 问题：可定位、可比较、可执行。"""

    code: str
    region: str
    message: str
    expected: float | None = None
    actual: float | None = None
    suggestion: str = ""

    def __str__(self) -> str:
        numbers = ""
        if self.expected is not None or self.actual is not None:
            numbers = f" (expected={self.expected}, actual={self.actual})"
        suggestion = f" suggestion: {self.suggestion}" if self.suggestion else ""
        return f"[{self.code}] {self.region or '<layout>'}: {self.message}{numbers}{suggestion}"


ConstraintFn = Callable[[LayoutGeometry], List[LayoutIssue]]

_CONSTRAINTS: dict[str, ConstraintFn] = {}


def register_constraint(fn: ConstraintFn) -> ConstraintFn:
    """零特权注册：内置与外部规则走同一通道；重名注册 fail fast。

    可直接调用 `register_constraint(fn)`，也可当装饰器用（返回原函数）。
    """
    name = getattr(fn, "__name__", "")
    if not name:
        raise ValueError("Layout constraint function must have a __name__")
    if name in _CONSTRAINTS:
        raise ValueError(f"Layout constraint already registered: {name}")
    _CONSTRAINTS[name] = fn
    return fn


def registered_constraints() -> List[ConstraintFn]:
    return list(_CONSTRAINTS.values())


def reset_constraints() -> None:
    """恢复为仅内置规则（测试与进程级重载用）。"""
    _CONSTRAINTS.clear()
    _register_builtin_constraints()


# ==================== 内置约束 ====================


@register_constraint
def _regions_within_safe_area(geo: LayoutGeometry) -> List[LayoutIssue]:
    issues: List[LayoutIssue] = []
    for name in geo.safe_region_names:
        region = geo.regions.get(name)
        if region is None:
            issues.append(LayoutIssue(
                code="unknown_region",
                region=name,
                message="region is listed as a safe region but not defined",
                suggestion="define the region or drop it from safe_region_names",
            ))
            continue
        if not geo.safe_area.contains(region):
            issues.append(LayoutIssue(
                code="outside_safe_area",
                region=name,
                message=(
                    f"region {name} {region.model_dump_json()} is not contained in "
                    f"safe area {geo.safe_area.model_dump_json()}"
                ),
                expected=None,
                actual=None,
                suggestion=(
                    f"clamp to x>={geo.safe_area.x}, y>={geo.safe_area.y}, "
                    f"right<={geo.safe_area.right}, bottom<={geo.safe_area.bottom}"
                ),
            ))
    return issues


@register_constraint
def _content_regions_disjoint(geo: LayoutGeometry) -> List[LayoutIssue]:
    issues: List[LayoutIssue] = []
    names = geo.content_region_names
    for i, left_name in enumerate(names):
        left = geo.regions.get(left_name)
        if left is None:
            continue
        for right_name in names[i + 1:]:
            right = geo.regions.get(right_name)
            if right is None:
                continue
            if left.overlaps(right):
                issues.append(LayoutIssue(
                    code="regions_overlap",
                    region=f"{left_name}+{right_name}",
                    message=(
                        f"content regions overlap: {left_name} "
                        f"{left.model_dump_json()} vs {right_name} "
                        f"{right.model_dump_json()}"
                    ),
                    expected=0.0,
                    actual=round(_overlap_area(left, right), 6),
                    suggestion=(
                        f"move {right_name} fully below/right of {left_name} "
                        "or shrink one of them until they touch edge-to-edge"
                    ),
                ))
    return issues


@register_constraint
def _regions_meet_min_size(geo: LayoutGeometry) -> List[LayoutIssue]:
    issues: List[LayoutIssue] = []
    for name, region in geo.regions.items():
        if region.width < MIN_REGION_WIDTH - 1e-9:
            issues.append(LayoutIssue(
                code="region_too_small",
                region=name,
                message=f"region {name} width below readable minimum",
                expected=MIN_REGION_WIDTH,
                actual=round(region.width, 6),
                suggestion=f"widen region {name} to at least {MIN_REGION_WIDTH}",
            ))
        if region.height < MIN_REGION_HEIGHT - 1e-9:
            issues.append(LayoutIssue(
                code="region_too_small",
                region=name,
                message=f"region {name} height below readable minimum",
                expected=MIN_REGION_HEIGHT,
                actual=round(region.height, 6),
                suggestion=f"raise region {name} height to at least {MIN_REGION_HEIGHT}",
            ))
    return issues


def _overlap_area(left: LayoutBox, right: LayoutBox) -> float:
    overlap_w = min(left.right, right.right) - max(left.x, right.x)
    overlap_h = min(left.bottom, right.bottom) - max(left.y, right.y)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return overlap_w * overlap_h


def _register_builtin_constraints() -> None:
    for fn in (_regions_within_safe_area, _content_regions_disjoint, _regions_meet_min_size):
        if fn.__name__ not in _CONSTRAINTS:
            register_constraint(fn)


_register_builtin_constraints()


# ==================== 裁决 ====================


def geometry_from_layout(layout: ComputedLayout) -> LayoutGeometry:
    return LayoutGeometry(
        frame_width=layout.frame_width,
        frame_height=layout.frame_height,
        safe_area=layout.safe_area,
        regions=dict(layout.regions),
        safe_region_names=tuple(layout.safe_region_names),
        content_region_names=tuple(layout.content_region_names),
    )


def judge_geometry(geo: LayoutGeometry) -> List[LayoutIssue]:
    """运行全部已注册约束，一次报出所有问题（注册顺序即报告顺序）。"""
    issues: List[LayoutIssue] = []
    for constraint in registered_constraints():
        issues.extend(constraint(geo))
    return issues


def judge_layout(layout: ComputedLayout) -> List[LayoutIssue]:
    return judge_geometry(geometry_from_layout(layout))


class LayoutValidationError(ValueError):
    """结构化 layout 校验失败：携带全部 LayoutIssue。"""

    def __init__(self, issues: List[LayoutIssue], scene_id: str = ""):
        self.issues = list(issues)
        prefix = f"scene {scene_id}: " if scene_id else ""
        detail = "; ".join(str(issue) for issue in self.issues)
        super().__init__(f"{prefix}{len(self.issues)} layout issue(s): {detail}")


# ==================== 外部约束模块加载 ====================


def constraint_module_spec(spec: str | None = None) -> list[str]:
    """取要加载的约束模块名列表（参数优先，否则读 env）。"""
    raw = spec if spec is not None else os.environ.get(LAYOUT_CONSTRAINTS_ENV, "")
    return [name.strip() for name in raw.split(",") if name.strip()]


def load_constraint_modules(spec: str | None = None) -> list[str]:
    """显式导入约束模块并执行其注册；导入/执行失败直接抛错（fail fast）。

    只接受 Python 模块路径；包 JSON 数据文件永远不在这里被加载或执行。
    """
    loaded: list[str] = []
    for module_name in constraint_module_spec(spec):
        importlib.import_module(module_name)
        loaded.append(module_name)
    return loaded
