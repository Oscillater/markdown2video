"""Coordinate mapping between normalized layout regions and concrete spaces.

The Manim renderer (center-origin, y-up unit space) and the FFmpeg assembler
(pixel space, top-left origin) both consume ``LayoutTemplate`` regions through
these helpers, so the two consumers cannot disagree about where a region is.
"""
from __future__ import annotations

from md2video.layout.schema import LayoutBox


def box_center_units(
    box: LayoutBox, frame_width: float, frame_height: float
) -> tuple[float, float]:
    """Center of a normalized top-left-origin box in center-origin, y-up units."""
    center_x = (box.x + box.width / 2 - 0.5) * frame_width
    center_y = (0.5 - (box.y + box.height / 2)) * frame_height
    return center_x, center_y


def box_size_units(
    box: LayoutBox, frame_width: float, frame_height: float
) -> tuple[float, float]:
    """Width and height of a normalized box in unit space."""
    return box.width * frame_width, box.height * frame_height


def box_pixel_rect(
    box: LayoutBox, frame_width: int, frame_height: int
) -> tuple[int, int, int, int]:
    """(left, top, width, height) in pixels with top-left origin."""
    left = round(box.x * frame_width)
    top = round(box.y * frame_height)
    width = round(box.width * frame_width)
    height = round(box.height * frame_height)
    return left, top, width, height


def even_size(width: int, height: int) -> tuple[int, int]:
    """Round dimensions down to even values, as required by some encoders."""
    return width - (width % 2), height - (height % 2)
