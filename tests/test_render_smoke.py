"""可选的像素级渲染冒烟测试：真实 Manim 渲染 + 真实 FFmpeg 合成。

运行方式::

    MD2VIDEO_RENDER_SMOKE=1 python -m pytest tests/test_render_smoke.py -q

验证 layout region 端到端生效：正文文字落在模板正文区域、per-shot 图片按
模板 image 区域摆放（Ken Burns cover 与静态 contain 两条路径）。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from md2video.assembler.ffmpeg_assembler import (
    FFmpegAssembler,
    attach_image_layout_regions,
)
from md2video.manifest.schema import (
    ExecutionAssets,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    ShotPlan,
    VisualAsset,
    result_manifest_from_execution_assets,
)
from md2video.tools.render.manim_tool import ManimRenderTool

pytestmark = pytest.mark.skipif(
    os.environ.get("MD2VIDEO_RENDER_SMOKE") != "1",
    reason="set MD2VIDEO_RENDER_SMOKE=1 to run the real render smoke test",
)

WIDTH, HEIGHT = 480, 854


def _make_image(path: Path, color, size=(300, 300)) -> None:
    Image.new("RGB", size, color).save(path)


def _build_plan(image_a: Path, image_b: Path) -> PlanManifest:
    return PlanManifest(
        segments=[
            SegmentPlan(id="title_main_001", text="布局冒烟测试", segment_type="title_main"),
            SegmentPlan(
                id="content_001", text="文字应该落在正文区域",
                segment_type="content", target_duration=1.0,
            ),
            SegmentPlan(
                id="content_002", text="上图下文 ken burns",
                segment_type="content", target_duration=1.5, explicit=True,
                visual_type="stock_image",
                visual_params={"preferred_provider": "local", "path": str(image_a)},
                layout_type="image_top_text_bottom",
            ),
            SegmentPlan(
                id="content_003", text="上图下文静态",
                segment_type="content", target_duration=0.8, explicit=True,
                visual_type="stock_image",
                visual_params={"preferred_provider": "local", "path": str(image_b)},
                layout_type="image_top_text_bottom",
            ),
        ],
        scenes=[
            ScenePlan(id="scene_001", shots=[ShotPlan(id="shot_001", segment_ids=["title_main_001"])]),
            ScenePlan(id="scene_002", shots=[ShotPlan(id="shot_002", segment_ids=["content_001"])]),
            ScenePlan(
                id="scene_003", visual_type="stock_image",
                visual_params={"preferred_provider": "local", "path": str(image_a)},
                layout_type="image_top_text_bottom",
                shots=[ShotPlan(id="shot_003", segment_ids=["content_002"])],
            ),
            ScenePlan(
                id="scene_004", visual_type="stock_image",
                visual_params={"preferred_provider": "local", "path": str(image_b)},
                layout_type="image_top_text_bottom",
                shots=[ShotPlan(id="shot_004", segment_ids=["content_003"])],
            ),
        ],
    )


def _probe_resolution(video: Path) -> str:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _extract_frame(video: Path, t: float, out: Path) -> Image.Image:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return Image.open(out).convert("RGB")


def _shot_mid(shots: dict, shot_id: str) -> float:
    shot = shots[shot_id]
    return (shot["start"] + shot["end"]) / 2


def _near(color, target, tol=70) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(color, target))


def _has_bright(im: Image.Image, x0, x1, y0, y1, step=2, threshold=400) -> bool:
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if sum(im.getpixel((x, y))) > threshold:
                return True
    return False


def test_render_smoke_places_text_and_images_by_layout(tmp_path):
    image_a = tmp_path / "red.png"
    image_b = tmp_path / "blue.png"
    _make_image(image_a, (255, 0, 0))
    _make_image(image_b, (0, 0, 255))

    plan = _build_plan(image_a, image_b)
    assets = ExecutionAssets(visual_assets=[
        VisualAsset(shot_id="shot_003", path=str(image_a), width=300, height=300, provider="local"),
        VisualAsset(shot_id="shot_004", path=str(image_b), width=300, height=300, provider="local"),
    ])

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    plan_path = artifacts / "plan.json"
    assets_path = artifacts / "execution-assets.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    assets_path.write_text(assets.model_dump_json(indent=2), encoding="utf-8")
    timeline_path = artifacts / "timeline.json"

    render_output = ManimRenderTool().execute({
        "plan_path": str(plan_path),
        "execution_assets_path": str(assets_path),
        "timeline_path": str(timeline_path),
        "output_dir": str(artifacts),
        "timeout": 600,
    })
    video_path = Path(render_output["video_path"])
    assert video_path.is_file()

    # 渲染分辨率必须来自 manim.cfg 的竖屏声明，不允许被质量旗标改成 16:9
    assert _probe_resolution(video_path) == f"{WIDTH}x{HEIGHT}"

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    shots = {shot["shot_id"]: shot for shot in timeline["shots"]}
    assert set(shots) == {"shot_001", "shot_002", "shot_003", "shot_004"}
    assert shots["shot_002"]["layout_type"] == "center_title_body"
    assert shots["shot_003"]["layout_type"] == "image_top_text_bottom"
    assert shots["shot_003"]["end"] > shots["shot_003"]["start"]

    # 真实 shot 时长决定 overlay 路径：>1s 走 Ken Burns，<=1s 走静态 contain
    assert shots["shot_003"]["end"] - shots["shot_003"]["start"] > 1.0
    assert shots["shot_004"]["end"] - shots["shot_004"]["start"] <= 1.0

    out_path = tmp_path / "output.mp4"
    result = result_manifest_from_execution_assets(plan, assets)
    FFmpegAssembler(
        plan, result, video_path, out_path,
        timeline_path=timeline_path, execution_assets=assets,
    ).assemble()
    assert out_path.is_file()
    assert _probe_resolution(out_path) == f"{WIDTH}x{HEIGHT}"

    # 与生产代码同一套 region 换算
    entry = {
        "layout_type": "image_top_text_bottom",
        "layout_params": {"split": "balanced", "gap": "normal"},
    }
    attach_image_layout_regions([entry], WIDTH, HEIGHT)
    region = entry["region_px"]
    center_x = region["left"] + region["width"] // 2
    center_y = region["top"] + region["height"] // 2

    # 像素断言全部针对合成后的交付视频
    # 正文文字落在 center_title_body 的 body region（中心 y_norm 0.62 -> py≈529）
    frame_body = _extract_frame(out_path, _shot_mid(shots, "shot_002"), tmp_path / "body.png")
    assert _has_bright(frame_body, 120, 360, 505, 555), "body text not found in body region"

    # Ken Burns 路径：图片 cover 整个 image region
    frame_kb = _extract_frame(out_path, _shot_mid(shots, "shot_003"), tmp_path / "kb.png")
    assert _near(frame_kb.getpixel((center_x, center_y)), (255, 0, 0)), \
        f"KB region center not red: {frame_kb.getpixel((center_x, center_y))}"
    assert _near(frame_kb.getpixel((region["left"] + 20, region["top"] + 20)), (255, 0, 0)), \
        "KB region corner not red"

    # 静态路径：图片 contain 进 image region，region 内边缘露出黑底
    frame_static = _extract_frame(out_path, _shot_mid(shots, "shot_004"), tmp_path / "static.png")
    assert _near(frame_static.getpixel((center_x, center_y)), (0, 0, 255)), \
        f"static region center not blue: {frame_static.getpixel((center_x, center_y))}"
    assert sum(frame_static.getpixel((region["left"] + 5, center_y))) < 120, \
        "static overlay should not cover the whole region (contain expected)"
    r, g, b = frame_static.getpixel((WIDTH // 2, 632))
    assert not _near((r, g, b), (0, 0, 255)), "image leaked into the text region"
