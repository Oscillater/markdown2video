from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from md2video.layout.schema import ComputedLayout, LayoutBox, LayoutParams, LayoutTemplate


SAFE_AREA = LayoutBox(x=0.08, y=0.06, width=0.84, height=0.88)


class CenterTitleBodyParams(LayoutParams):
    model_config = ConfigDict(extra="forbid")

    density: Literal["normal", "compact"] = "normal"


class FullBleedImageCaptionBottomParams(LayoutParams):
    model_config = ConfigDict(extra="forbid")

    caption_size: Literal["normal", "compact"] = "normal"


class ImageTopTextBottomParams(LayoutParams):
    model_config = ConfigDict(extra="forbid")

    split: Literal["balanced", "image_focus", "text_focus"] = "balanced"
    gap: Literal["normal", "wide"] = "normal"


def _center_title_body(params, frame_width: int, frame_height: int) -> ComputedLayout:
    title_height = 0.16 if params.density == "compact" else 0.20
    gap = 0.04
    body_y = SAFE_AREA.y + title_height + gap
    body_height = SAFE_AREA.bottom - body_y
    return ComputedLayout(
        template_id="center_title_body",
        frame_width=frame_width,
        frame_height=frame_height,
        safe_area=SAFE_AREA,
        regions={
            "title": LayoutBox(
                x=SAFE_AREA.x,
                y=SAFE_AREA.y,
                width=SAFE_AREA.width,
                height=title_height,
            ),
            "body": LayoutBox(
                x=SAFE_AREA.x,
                y=body_y,
                width=SAFE_AREA.width,
                height=body_height,
            ),
        },
        safe_region_names=["title", "body"],
        content_region_names=["title", "body"],
    )


def _full_bleed_image_caption_bottom(params, frame_width: int, frame_height: int) -> ComputedLayout:
    caption_height = 0.14 if params.caption_size == "compact" else 0.18
    return ComputedLayout(
        template_id="full_bleed_image_caption_bottom",
        frame_width=frame_width,
        frame_height=frame_height,
        safe_area=SAFE_AREA,
        regions={
            "image": LayoutBox(x=0.0, y=0.0, width=1.0, height=1.0),
            "caption": LayoutBox(
                x=SAFE_AREA.x,
                y=SAFE_AREA.bottom - caption_height,
                width=SAFE_AREA.width,
                height=caption_height,
            ),
        },
        safe_region_names=["caption"],
        content_region_names=["caption"],
    )


def _image_top_text_bottom(params, frame_width: int, frame_height: int) -> ComputedLayout:
    ratios = {
        "balanced": 0.50,
        "image_focus": 0.58,
        "text_focus": 0.42,
    }
    gap = 0.04 if params.gap == "normal" else 0.06
    image_height = SAFE_AREA.height * ratios[params.split]
    text_y = SAFE_AREA.y + image_height + gap
    text_height = SAFE_AREA.bottom - text_y
    return ComputedLayout(
        template_id="image_top_text_bottom",
        frame_width=frame_width,
        frame_height=frame_height,
        safe_area=SAFE_AREA,
        regions={
            "image": LayoutBox(
                x=SAFE_AREA.x,
                y=SAFE_AREA.y,
                width=SAFE_AREA.width,
                height=image_height,
            ),
            "text": LayoutBox(
                x=SAFE_AREA.x,
                y=text_y,
                width=SAFE_AREA.width,
                height=text_height,
            ),
        },
        safe_region_names=["image", "text"],
        content_region_names=["image", "text"],
    )


BUILTIN_TEMPLATES = [
    LayoutTemplate(
        id="center_title_body",
        params_model=CenterTitleBodyParams,
        compute_func=_center_title_body,
    ),
    LayoutTemplate(
        id="full_bleed_image_caption_bottom",
        params_model=FullBleedImageCaptionBottomParams,
        compute_func=_full_bleed_image_caption_bottom,
    ),
    LayoutTemplate(
        id="image_top_text_bottom",
        params_model=ImageTopTextBottomParams,
        compute_func=_image_top_text_bottom,
    ),
]
