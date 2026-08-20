from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_LAYOUT_TYPE = "center_title_body"


class LayoutBox(BaseModel):
    """A normalized rectangle using a top-left origin."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _inside_frame(self):
        if self.x + self.width > 1.0 + 1e-9:
            raise ValueError("layout box exceeds frame width")
        if self.y + self.height > 1.0 + 1e-9:
            raise ValueError("layout box exceeds frame height")
        return self

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, other: "LayoutBox") -> bool:
        eps = 1e-9
        return (
            other.x >= self.x - eps
            and other.y >= self.y - eps
            and other.right <= self.right + eps
            and other.bottom <= self.bottom + eps
        )

    def overlaps(self, other: "LayoutBox") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )


class ComputedLayout(BaseModel):
    """Computed regions for a layout template."""

    template_id: str
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    safe_area: LayoutBox
    regions: Dict[str, LayoutBox]
    safe_region_names: list[str] = Field(default_factory=list)
    content_region_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_regions(self):
        for name in self.safe_region_names:
            if name not in self.regions:
                raise ValueError(f"unknown safe region: {name}")
            if not self.safe_area.contains(self.regions[name]):
                raise ValueError(f"region outside safe area: {name}")

        for name in self.content_region_names:
            if name not in self.regions:
                raise ValueError(f"unknown content region: {name}")

        for idx, left_name in enumerate(self.content_region_names):
            left = self.regions[left_name]
            for right_name in self.content_region_names[idx + 1:]:
                if left.overlaps(self.regions[right_name]):
                    raise ValueError(
                        f"content regions overlap: {left_name}, {right_name}"
                    )
        return self

    def region(self, name: str) -> LayoutBox:
        return self.regions[name]


class LayoutParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class LayoutTemplate:
    id: str
    params_model: Type[BaseModel]
    compute_func: Callable[[BaseModel, int, int], ComputedLayout]

    def validate_params(self, params: Mapping[str, Any] | None = None) -> BaseModel:
        return self.params_model.model_validate(dict(params or {}))

    def compute(
        self,
        params: Mapping[str, Any] | None,
        frame_width: int,
        frame_height: int,
    ) -> ComputedLayout:
        parsed = self.validate_params(params)
        return self.compute_func(parsed, frame_width, frame_height)


def iter_box_names(layout: ComputedLayout, names: Iterable[str]) -> Iterable[tuple[str, LayoutBox]]:
    for name in names:
        yield name, layout.regions[name]
