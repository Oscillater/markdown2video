"""可选的 Remotion 真渲染冒烟测试（A6 后半验收）。

运行方式::

    MD2VIDEO_RENDER_SMOKE=1 python -m pytest tests/test_remotion_smoke.py -q

前置：Node 22+ 与 `md2video/tools/render/remotion_backend` 内 `npm install`
（首次渲染会自动下载 headless shell）。全静默 plan：不依赖 TTS 与网络。

验收点：Remotion 后端走同一渲染契约（同构 timeline + 同一道时间闸门），
成片分辨率 480x854、时长与调度一致、标题/正文按 layout 区域落位、
双跑逐帧一致（确定性）。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from md2video.manifest.schema import ExecutionAssets, PlanManifest, SegmentPlan
from md2video.tools.render.remotion_tool import RemotionRenderTool

pytestmark = pytest.mark.skipif(
    os.environ.get("MD2VIDEO_RENDER_SMOKE") != "1",
    reason="set MD2VIDEO_RENDER_SMOKE=1 to run the real Remotion render smoke test",
)

WIDTH, HEIGHT = 480, 854


def _build_plan() -> PlanManifest:
    return PlanManifest(
        segments=[
            SegmentPlan(id="title_main_001", text="Remotion 冒烟", segment_type="title_main"),
            SegmentPlan(id="header_001", text="第一节", segment_type="section_header"),
            SegmentPlan(id="content_001", text="正文应该落在正文区域", segment_type="content"),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "shots": [
                {"id": "shot_001", "segment_ids": ["title_main_001"]},
                {"id": "shot_002", "segment_ids": ["header_001"]},
                {"id": "shot_003", "segment_ids": ["content_001"]},
            ],
            "section_context": "smoke",
        }],
    )


def _write_manifests(tmp_path: Path) -> tuple[Path, Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    plan_path = artifacts / "plan.json"
    plan_path.write_text(_build_plan().model_dump_json(indent=2), encoding="utf-8")
    assets_path = artifacts / "execution-assets.json"
    assets_path.write_text(ExecutionAssets().model_dump_json(indent=2), encoding="utf-8")
    return plan_path, assets_path


def _render(plan_path: Path, assets_path: Path, output_dir: Path) -> dict:
    return RemotionRenderTool().execute({
        "plan_path": str(plan_path),
        "execution_assets_path": str(assets_path),
        "timeline_path": str(output_dir / "timeline.json"),
        "output_dir": str(output_dir),
        "timeout": 900,
    })


def _probe_resolution(video: Path) -> str:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(proc.stdout).get("streams") or []
    first = streams[0]
    return f"{first['width']}x{first['height']}"


def _probe_duration(video: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def _framemd5(video: Path) -> str:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "framemd5", "-"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def _extract_frame(video: Path, t: float, out: Path) -> Image.Image:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return Image.open(out).convert("RGB")


def _has_bright(im: Image.Image, x0, x1, y0, y1, step=2, threshold=400) -> bool:
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if sum(im.getpixel((x, y))) > threshold:
                return True
    return False


def _bright_in_rect(im: Image.Image, rect, padding=8) -> bool:
    left, top, width, height = rect
    return _has_bright(
        im,
        left + padding,
        left + width - padding,
        top + padding,
        top + height - padding,
    )


def test_remotion_smoke_contract_and_determinism(tmp_path):
    plan_path, assets_path = _write_manifests(tmp_path)

    run_a = tmp_path / "run_a"
    run_a.mkdir()
    output_a = _render(plan_path, assets_path, run_a)
    video_a = Path(output_a["video_path"])
    assert video_a.is_file()

    # 渲染契约：分辨率与时长
    assert _probe_resolution(video_a) == f"{WIDTH}x{HEIGHT}"

    timeline = json.loads((run_a / "timeline.json").read_text(encoding="utf-8"))
    shots = {shot["shot_id"]: shot for shot in timeline["shots"]}
    assert set(shots) == {"shot_001", "shot_002", "shot_003"}
    total = shots["shot_003"]["end"]
    # ink_night：title_hold 1.0 + section_header 0.5 + body 2.0
    assert total == pytest.approx(3.5, abs=1e-6)
    assert _probe_duration(video_a) == pytest.approx(total, abs=0.3)

    # 区域矩形来自调度 props（layout 契约的像素换算）
    props = json.loads((run_a / "remotion_props.json").read_text(encoding="utf-8"))
    props_shots = {shot["shot_id"]: shot for shot in props["shots"]}

    # 落位断言：黑底白字 → 在目标区域内找亮像素
    frame_title = _extract_frame(video_a, 0.5, tmp_path / "title.png")
    assert _bright_in_rect(frame_title, props_shots["shot_001"]["regions"]["title"]), \
        "title text not found in title region"

    frame_body = _extract_frame(
        video_a, shots["shot_003"]["start"] + 0.5, tmp_path / "body.png"
    )
    body_rect = next(
        rect for name, rect in props_shots["shot_003"]["regions"].items()
        if name in ("body", "text", "caption")
    )
    assert _bright_in_rect(frame_body, body_rect), "body text not found in body region"

    # 确定性：同一 props 再渲染一次，逐帧 framemd5 一致
    run_b = tmp_path / "run_b"
    run_b.mkdir()
    output_b = _render(plan_path, assets_path, run_b)
    video_b = Path(output_b["video_path"])
    assert _framemd5(video_a) == _framemd5(video_b)


def test_mixed_manim_remotion_plan_produces_one_video(tmp_path):
    """混合 manim/remotion：管线分组切片 → 各后端渲染 → 拼接 → 一条成片。"""
    from md2video.core.pipeline import Pipeline

    plan = PlanManifest(
        segments=[
            SegmentPlan(id="content_001", text="manim 组正文", segment_type="content"),
            SegmentPlan(id="content_002", text="remotion 组正文", segment_type="content"),
        ],
        scenes=[
            {
                "id": "scene_001",
                "visual_type": "text_only",
                "visual_params": {},
                "shots": [{"id": "shot_001", "segment_ids": ["content_001"]}],
                "section_context": "manim",
            },
            {
                "id": "scene_002",
                "visual_type": "text_only",
                "visual_params": {},
                "render_backend": "remotion",
                "shots": [{"id": "shot_002", "segment_ids": ["content_002"]}],
                "section_context": "remotion",
            },
        ],
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    plan_path = artifacts / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    output_path = tmp_path / "mixed.mp4"

    pipeline = Pipeline(artifacts_dir=artifacts)
    result = pipeline.run_plan(str(plan_path), str(output_path))
    assert result == output_path
    assert output_path.is_file()

    raw_result = json.loads(
        ((artifacts / "runs") / sorted(os.listdir(artifacts / "runs"))[0] / "result.json")
        .read_text(encoding="utf-8")
    )
    assert raw_result["status"] == "completed"
    assert raw_result["artifact_index"]["render_provider"] == "manim+remotion"
