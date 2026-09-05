"""Tests for normalized layout region coordinate mapping."""
from __future__ import annotations

import pytest

from md2video.layout.mapping import (
    box_center_units,
    box_pixel_rect,
    box_size_units,
    even_size,
)
from md2video.layout.schema import LayoutBox


def test_full_frame_box_center_is_origin():
    box = LayoutBox(x=0.0, y=0.0, width=1.0, height=1.0)

    assert box_center_units(box, 4.5, 8.0) == (0.0, 0.0)
    assert box_size_units(box, 4.5, 8.0) == (4.5, 8.0)


def test_top_left_box_maps_to_negative_x_positive_y():
    box = LayoutBox(x=0.0, y=0.0, width=0.25, height=0.25)

    assert box_center_units(box, 4.0, 8.0) == (-1.5, 3.0)


def test_bottom_right_box_maps_to_positive_x_negative_y():
    box = LayoutBox(x=0.75, y=0.75, width=0.25, height=0.25)

    assert box_center_units(box, 4.0, 8.0) == (1.5, -3.0)


def test_box_size_units_scales_with_frame():
    box = LayoutBox(x=0.08, y=0.06, width=0.84, height=0.88)

    assert box_size_units(box, 4.5, 8.0) == (pytest.approx(3.78), pytest.approx(7.04))


def test_box_pixel_rect_rounds_to_integers():
    box = LayoutBox(x=0.08, y=0.06, width=0.84, height=0.88)

    assert box_pixel_rect(box, 480, 854) == (38, 51, 403, 752)


def test_box_pixel_rect_full_frame():
    box = LayoutBox(x=0.0, y=0.0, width=1.0, height=1.0)

    assert box_pixel_rect(box, 480, 854) == (0, 0, 480, 854)


def test_even_size_rounds_down_to_even():
    assert even_size(403, 751) == (402, 750)
    assert even_size(402, 376) == (402, 376)
    assert even_size(1, 1) == (0, 0)
