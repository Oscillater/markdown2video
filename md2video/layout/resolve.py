"""Scene layout 解析：直接提案与模板产出走同一套约束裁决（A5）。

提案者平等：`ScenePlan.layout_regions` 直接提案、内置模板、（未来的）
LLM/用户提案都产出候选 region 集合，由 `layout/constraints.py` 的同一
个注册表裁决。提案里名字为 image 的 region 视为视觉槽位（与内置
full_bleed 模板一致）：可以全屏出血、允许文字叠在其上，因此豁免安全区
与重叠检查；其余 region 都是内容 region（安全区内、互不重叠）。
"""
from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError

from md2video.layout.constraints import (
    LayoutIssue,
    LayoutValidationError,
    judge_geometry,
)
from md2video.layout.registry import LayoutRegistry, create_default_layout_registry
from md2video.layout.schema import ComputedLayout, LayoutBox
from md2video.layout.templates import SAFE_AREA

PROPOSAL_TEMPLATE_ID = "proposal"

# 视觉槽位：全屏/出血可叠字（对齐内置模板对 image region 的用法）
IMAGE_SLOT_REGION_NAMES = {"image"}


def evaluate_layout_proposal(
    proposal: Mapping[str, Any],
    frame_width: int,
    frame_height: int,
) -> tuple[ComputedLayout | None, list[LayoutIssue]]:
    """裁决一个 regions 直接提案；返回 (布局 | None, 全部问题)。"""
    regions: dict[str, LayoutBox] = {}
    issues: list[LayoutIssue] = []
    for name, box_data in dict(proposal).items():
        try:
            regions[str(name)] = LayoutBox.model_validate(box_data)
        except ValidationError as exc:
            issues.append(LayoutIssue(
                code="invalid_box",
                region=str(name),
                message=f"region {name} is not a valid normalized box: {exc.error_count()} error(s)",
                suggestion=(
                    "provide x/y/width/height floats with x,y>=0, x+width<=1, "
                    f"y+height<=1; pydantic said: {exc.errors()[0].get('msg', '')}"
                ),
            ))
    if issues:
        return None, issues

    content_names = tuple(
        name for name in regions if name not in IMAGE_SLOT_REGION_NAMES
    )
    from md2video.layout.constraints import LayoutGeometry
    geometry = LayoutGeometry(
        frame_width=frame_width,
        frame_height=frame_height,
        safe_area=SAFE_AREA,
        regions=regions,
        safe_region_names=content_names,
        content_region_names=content_names,
    )
    issues = judge_geometry(geometry)
    if issues:
        return None, issues

    layout = ComputedLayout(
        template_id=PROPOSAL_TEMPLATE_ID,
        frame_width=frame_width,
        frame_height=frame_height,
        safe_area=SAFE_AREA,
        regions=regions,
        safe_region_names=list(content_names),
        content_region_names=list(content_names),
    )
    return layout, []


def resolve_scene_layout(
    layout_type: str,
    layout_params: Mapping[str, Any] | None,
    layout_regions: Mapping[str, Any] | None,
    frame_width: int,
    frame_height: int,
    registry: LayoutRegistry | None = None,
) -> ComputedLayout:
    """解析一个 scene 的最终布局；非法输入抛 LayoutValidationError（含全部 issue）。

    `layout_regions` 直接提案优先于 `layout_type` 模板。
    """
    if layout_regions:
        layout, issues = evaluate_layout_proposal(layout_regions, frame_width, frame_height)
        if issues:
            raise LayoutValidationError(issues)
        return layout

    active_registry = registry or create_default_layout_registry()
    try:
        layout = active_registry.compute(layout_type, layout_params, frame_width, frame_height)
    except LayoutValidationError:
        raise
    except Exception as exc:
        raise LayoutValidationError([LayoutIssue(
            code="invalid_template_layout",
            region="",
            message=f"layout_type {layout_type!r} failed to compute: {exc}",
            suggestion="check layout_type name and layout_params against the template schema",
        )]) from exc
    # 模板产出与提案过同一套属性校验（内置模板应当全过；外部模板可能不过）
    from md2video.layout.constraints import judge_layout
    issues = judge_layout(layout)
    if issues:
        raise LayoutValidationError(issues)
    return layout
