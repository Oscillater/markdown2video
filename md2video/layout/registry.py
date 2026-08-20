from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from md2video.config import MANIM_HEIGHT, MANIM_WIDTH
from md2video.layout.schema import ComputedLayout, LayoutTemplate
from md2video.layout.templates import BUILTIN_TEMPLATES


class LayoutRegistry:
    def __init__(self, templates: Iterable[LayoutTemplate] | None = None):
        self._templates: dict[str, LayoutTemplate] = {}
        for template in templates or []:
            self.register(template)

    def register(self, template: LayoutTemplate, *, replace: bool = False) -> None:
        if not replace and template.id in self._templates:
            raise ValueError(f"Duplicate layout template id: {template.id}")
        self._templates[template.id] = template

    def get(self, layout_type: str) -> LayoutTemplate | None:
        return self._templates.get(layout_type)

    def require(self, layout_type: str) -> LayoutTemplate:
        template = self.get(layout_type)
        if not template:
            raise ValueError(f"Unknown layout_type: {layout_type}")
        return template

    def validate(self, layout_type: str, params: Mapping[str, Any] | None = None):
        return self.require(layout_type).validate_params(params)

    def compute(
        self,
        layout_type: str,
        params: Mapping[str, Any] | None = None,
        frame_width: int = MANIM_WIDTH,
        frame_height: int = MANIM_HEIGHT,
    ) -> ComputedLayout:
        return self.require(layout_type).compute(params, frame_width, frame_height)

    def list_ids(self) -> list[str]:
        return list(self._templates.keys())


def create_default_layout_registry() -> LayoutRegistry:
    return LayoutRegistry(BUILTIN_TEMPLATES)
