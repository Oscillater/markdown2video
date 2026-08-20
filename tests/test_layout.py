from __future__ import annotations

import pytest
from pydantic import ValidationError

from md2video.config import MANIM_HEIGHT, MANIM_WIDTH
from md2video.layout import create_default_layout_registry
from md2video.layout.schema import LayoutBox


def test_default_registry_contains_builtin_templates():
    registry = create_default_layout_registry()

    assert registry.list_ids() == [
        "center_title_body",
        "full_bleed_image_caption_bottom",
        "image_top_text_bottom",
    ]


def test_unknown_layout_raises():
    registry = create_default_layout_registry()

    with pytest.raises(ValueError, match="Unknown layout_type"):
        registry.compute("missing_layout", {})


def test_duplicate_layout_registration_raises():
    registry = create_default_layout_registry()
    template = registry.require("center_title_body")

    with pytest.raises(ValueError, match="Duplicate layout template id"):
        registry.register(template)

    registry.register(template, replace=True)


def test_invalid_params_raise():
    registry = create_default_layout_registry()

    with pytest.raises(ValidationError):
        registry.compute("center_title_body", {"density": "giant"})

    with pytest.raises(ValidationError):
        registry.compute("image_top_text_bottom", {"x": 0.2})

    with pytest.raises(ValidationError):
        registry.compute(
            "full_bleed_image_caption_bottom",
            {"caption_background": "solid"},
        )


@pytest.mark.parametrize(
    ("layout_type", "params"),
    [
        ("center_title_body", {}),
        ("center_title_body", {"density": "compact"}),
        ("full_bleed_image_caption_bottom", {}),
        ("full_bleed_image_caption_bottom", {"caption_size": "compact"}),
        ("image_top_text_bottom", {}),
        ("image_top_text_bottom", {"split": "image_focus", "gap": "wide"}),
        ("image_top_text_bottom", {"split": "text_focus"}),
    ],
)
def test_builtin_layout_valid_parameter_combinations(layout_type, params):
    layout = create_default_layout_registry().compute(layout_type, params)

    assert layout.template_id == layout_type
    assert layout.frame_width == MANIM_WIDTH
    assert layout.frame_height == MANIM_HEIGHT

    for box in layout.regions.values():
        assert box.x >= 0.0
        assert box.y >= 0.0
        assert box.right <= 1.0
        assert box.bottom <= 1.0

    for name in layout.safe_region_names:
        assert layout.safe_area.contains(layout.region(name))

    for idx, left_name in enumerate(layout.content_region_names):
        left = layout.region(left_name)
        for right_name in layout.content_region_names[idx + 1:]:
            assert not left.overlaps(layout.region(right_name))


def test_center_title_body_regions_are_safe_and_non_overlapping():
    layout = create_default_layout_registry().compute("center_title_body", {})

    assert layout.frame_width == MANIM_WIDTH
    assert layout.frame_height == MANIM_HEIGHT
    assert layout.safe_area.contains(layout.region("title"))
    assert layout.safe_area.contains(layout.region("body"))
    assert not layout.region("title").overlaps(layout.region("body"))


def test_full_bleed_image_allows_background_caption_overlap():
    layout = create_default_layout_registry().compute(
        "full_bleed_image_caption_bottom", {}
    )

    assert layout.region("image") == LayoutBox(x=0.0, y=0.0, width=1.0, height=1.0)
    assert layout.region("image").overlaps(layout.region("caption"))
    assert layout.safe_area.contains(layout.region("caption"))
    assert layout.content_region_names == ["caption"]


def test_image_top_text_bottom_regions_are_safe_and_non_overlapping():
    layout = create_default_layout_registry().compute(
        "image_top_text_bottom", {"split": "image_focus", "gap": "wide"}
    )

    assert layout.safe_area.contains(layout.region("image"))
    assert layout.safe_area.contains(layout.region("text"))
    assert not layout.region("image").overlaps(layout.region("text"))
