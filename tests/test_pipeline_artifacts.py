from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from md2video.config import ToolConfig
from md2video.core.pipeline import Pipeline
from md2video.manifest.schema import (
    AudioRequest,
    ExecutionAssets,
    FinalResultManifest,
    PlanManifest,
    SegmentPlan,
)
from md2video.tools.image.local_image_tool import LocalImageTool
from md2video.tools.registry import ToolRegistry


class FakeRenderTool:
    provider_name = "manim"
    tool_type = "render"

    def __init__(self, tmp_path: Path, output=None, write_artifacts: bool = True):
        self.tmp_path = tmp_path
        self.output = output
        self.write_artifacts = write_artifacts
        self.calls = []

    def execute(self, input_data):
        self.calls.append(input_data)
        # 真实渲染后端的产物落进管线指定的 output_dir（run 目录）
        output_dir = Path(input_data["output_dir"])
        video_path = output_dir / "base.mp4"
        timeline_path = Path(input_data["timeline_path"])
        render_dir = output_dir / "manim_render_fake"
        if self.write_artifacts:
            video_path.write_bytes(b"fake mp4")
            timeline_path.write_text(
                json.dumps({"text": [], "markers": [], "shots": []}),
                encoding="utf-8",
            )
            render_dir.mkdir(parents=True, exist_ok=True)
        if self.output is not None:
            return self.output
        return {
            "video_path": str(video_path),
            "timeline_path": str(timeline_path),
            "provider": "manim",
            "render_dir": str(render_dir),
        }


def _sole_run_dir(tmp_path: Path) -> Path:
    runs = sorted((tmp_path / "runs").iterdir())
    assert len(runs) == 1, f"expected exactly one run dir, got {runs}"
    return runs[0]


def _make_pipeline(tmp_path, voice=None, speed=None, render_tool=None):
    with patch.object(Pipeline, "_create_planner"):
        with patch.object(Pipeline, "_register_default_tools"):
            pipeline = Pipeline(
                artifacts_dir=tmp_path,
                tool_config=ToolConfig(priority={"stock_image": ["local"]}),
                voice=voice,
                speed=speed,
            )
    registry = ToolRegistry()
    registry.register("stock_image", LocalImageTool())
    registry.register("render", render_tool or FakeRenderTool(tmp_path))
    pipeline.registry = registry
    return pipeline


def _write_stock_image_plan(tmp_path: Path) -> tuple[Path, Path]:
    image_path = tmp_path / "local_image.jpg"
    Image.new("RGB", (500, 631), color=(32, 96, 160)).save(image_path)
    plan_path = tmp_path / "stock_image_plan.json"
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="seg_001",
                text="Local image manifest test.",
                segment_type="content",
                audio_request=None,
            ),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "stock_image",
            "visual_params": {
                "preferred_provider": "local",
                "path": image_path.name,
            },
            "shots": [{
                "id": "shot_001",
                "segment_ids": ["seg_001"],
            }],
            "section_context": "local image test",
        }],
        media_declarations={},
    )
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return plan_path, image_path


def test_run_plan_writes_execution_assets_and_final_result(tmp_path):
    plan_path, image_path = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"

    pipeline = _make_pipeline(tmp_path)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        result = pipeline.run_plan(str(plan_path), str(output_path))

    assert result == output_path
    run_dir = _sole_run_dir(tmp_path)
    render_tool = pipeline.registry.get_tool("render", "manim")
    assert len(render_tool.calls) == 1
    render_input = render_tool.calls[0]
    assert render_input["plan_path"] == str(run_dir / "plan.json")
    assert render_input["execution_assets_path"] == str(run_dir / "execution-assets.json")
    assert render_input["timeline_path"] == str(run_dir / "timeline.json")
    assert render_input["output_dir"] == str(run_dir)

    assets_path = run_dir / "execution-assets.json"
    assets = ExecutionAssets.model_validate_json(assets_path.read_text(encoding="utf-8"))
    assert len(assets.audio_assets) == 0
    assert len(assets.visual_assets) == 1
    assert assets.visual_assets[0].shot_id == "shot_001"
    assert assets.visual_assets[0].provider == "local"
    assert assets.visual_assets[0].path == str(image_path.resolve())

    assembler_cls.assert_called_once()
    assert assembler_cls.call_args.kwargs["execution_assets"].visual_assets[0].provider == "local"

    final_result = FinalResultManifest.model_validate_json(
        (run_dir / "result.json").read_text(encoding="utf-8"),
    )
    assert final_result.output_mp4 == str(output_path)
    assert final_result.status == "completed"
    assert final_result.run_id == run_dir.name
    assert final_result.artifact_index["execution_assets"] == str(assets_path)
    assert final_result.artifact_index["base_video"] == str(run_dir / "base.mp4")
    assert final_result.artifact_index["render_dir"] == str(run_dir / "manim_render_fake")
    assert final_result.artifact_index["render_provider"] == "manim"
    assert final_result.artifact_index["manifest_viewer"] == str(run_dir / "manifest_viewer.html")
    assert final_result.used_assets["visual"][0]["shot_id"] == "shot_001"

    # 检查页是单文件自包含（有内容、含 run id），与四本账同住 run 目录
    viewer_html = (run_dir / "manifest_viewer.html").read_text(encoding="utf-8")
    assert run_dir.name in viewer_html

    raw_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert "segments" not in raw_result


def test_run_plan_rejects_render_output_missing_fields_before_assembler(tmp_path):
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    render_tool = FakeRenderTool(
        tmp_path,
        output={
            "video_path": str(tmp_path / "base.mp4"),
            "timeline_path": str(tmp_path / "timeline.json"),
            "provider": "manim",
        },
    )
    pipeline = _make_pipeline(tmp_path, render_tool=render_tool)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        with pytest.raises(RuntimeError, match="missing fields.*render_dir"):
            pipeline.run_plan(str(plan_path), str(output_path))

    assembler_cls.assert_not_called()


def test_run_plan_rejects_missing_render_artifacts_before_assembler(tmp_path):
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    render_tool = FakeRenderTool(tmp_path, write_artifacts=False)
    pipeline = _make_pipeline(tmp_path, render_tool=render_tool)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        with pytest.raises(RuntimeError, match="missing artifacts.*base.mp4"):
            pipeline.run_plan(str(plan_path), str(output_path))

    assembler_cls.assert_not_called()


def test_run_plan_rejects_unexpected_render_timeline_before_assembler(tmp_path):
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    old_timeline_path = tmp_path / "old-timeline.json"
    old_timeline_path.write_text(
        json.dumps({"text": [], "markers": [], "shots": []}),
        encoding="utf-8",
    )
    render_tool = FakeRenderTool(
        tmp_path,
        output={
            "video_path": str(tmp_path / "base.mp4"),
            "timeline_path": str(old_timeline_path),
            "provider": "manim",
            "render_dir": str(tmp_path / "manim_render_fake"),
        },
    )
    pipeline = _make_pipeline(tmp_path, render_tool=render_tool)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        with pytest.raises(RuntimeError, match="unexpected timeline_path.*old-timeline"):
            pipeline.run_plan(str(plan_path), str(output_path))

    assembler_cls.assert_not_called()


def test_run_plan_rejects_unexpected_render_provider_before_assembler(tmp_path):
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    render_tool = FakeRenderTool(
        tmp_path,
        output={
            "video_path": str(tmp_path / "base.mp4"),
            "timeline_path": str(tmp_path / "timeline.json"),
            "provider": "other-renderer",
            "render_dir": str(tmp_path / "manim_render_fake"),
        },
    )
    pipeline = _make_pipeline(tmp_path, render_tool=render_tool)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        with pytest.raises(RuntimeError, match="unexpected provider.*other-renderer"):
            pipeline.run_plan(str(plan_path), str(output_path))

    assembler_cls.assert_not_called()


# ========== render backend 去硬编码（A2.5）==========


class FakeAltRenderTool:
    """provider 非 manim 的渲染后端：整条切换验收用。"""

    provider_name = "fake-backend"
    tool_type = "render"

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls = []

    def execute(self, input_data):
        self.calls.append(input_data)
        output_dir = Path(input_data["output_dir"])
        video_path = output_dir / "alt_base.mp4"
        video_path.write_bytes(b"fake alt mp4")
        timeline_path = Path(input_data["timeline_path"])
        timeline_path.write_text(
            json.dumps({"text": [], "markers": [], "shots": []}),
            encoding="utf-8",
        )
        render_dir = output_dir / "fake_backend_render"
        render_dir.mkdir(parents=True, exist_ok=True)
        return {
            "video_path": str(video_path),
            "timeline_path": str(timeline_path),
            "provider": self.provider_name,
            "render_dir": str(render_dir),
        }


def test_run_plan_switches_to_registered_alternate_backend(tmp_path):
    """配置切到新后端后整条 run_plan 走通，不改管线代码。"""
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"

    pipeline = _make_pipeline(tmp_path)
    alt_tool = FakeAltRenderTool(tmp_path)
    pipeline.registry.register("render", alt_tool)
    pipeline.tool_config.render_backend = "fake-backend"

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        result = pipeline.run_plan(str(plan_path), str(output_path))

    assert result == output_path
    run_dir = _sole_run_dir(tmp_path)
    assert len(alt_tool.calls) == 1
    assert alt_tool.calls[0]["timeline_path"] == str(run_dir / "timeline.json")
    assembler_cls.assert_called_once()

    final_result = FinalResultManifest.model_validate_json(
        (run_dir / "result.json").read_text(encoding="utf-8"),
    )
    assert final_result.artifact_index["render_provider"] == "fake-backend"
    assert final_result.artifact_index["base_video"] == str(run_dir / "alt_base.mp4")


def test_run_plan_fails_fast_when_configured_backend_not_registered(tmp_path):
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"

    pipeline = _make_pipeline(tmp_path)
    pipeline.tool_config.render_backend = "not-registered"

    with pytest.raises(ValueError, match="Render tool not registered: render/not-registered"):
        pipeline.run_plan(str(plan_path), str(output_path))


def test_load_tool_config_reads_render_backend_env(monkeypatch):
    from md2video.config import load_tool_config

    monkeypatch.delenv("MD2VIDEO_RENDER_BACKEND", raising=False)
    assert load_tool_config().render_backend == "manim"

    monkeypatch.setenv("MD2VIDEO_RENDER_BACKEND", "remotion")
    assert load_tool_config().render_backend == "remotion"


def test_tts_assets_use_cli_voice_speed_overrides_and_absolute_paths(tmp_path):
    class FakeTTSTool:
        provider_name = "edge-tts"

        def __init__(self):
            self.calls = []

        def execute(self, input_data):
            self.calls.append(input_data)
            return {
                "path": str(tmp_path / "tts" / "seg_001.wav"),
                "duration": 1.5,
                "provider": "edge-tts",
                "cache_key": "fake-key",
            }

    pipeline = _make_pipeline(tmp_path, voice="en-US-JennyNeural", speed=1.25)
    fake_tts = FakeTTSTool()
    pipeline.registry.register("tts", fake_tts)

    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="seg_001",
                text="hello",
                segment_type="content",
                audio_request=AudioRequest(),
            ),
        ],
    )

    assets = pipeline._prepare_execution_assets(plan)

    assert fake_tts.calls[0]["voice"] == "en-US-JennyNeural"
    assert fake_tts.calls[0]["speed"] == 1.25
    assert Path(assets.audio_assets[0].path).is_absolute()


def test_tts_assets_skip_title_segments(tmp_path):
    class FakeTTSTool:
        provider_name = "edge-tts"

        def __init__(self):
            self.calls = []

        def execute(self, input_data):
            self.calls.append(input_data)
            return {
                "path": str(tmp_path / "tts" / f"{len(self.calls)}.wav"),
                "duration": 1.0,
                "provider": "edge-tts",
                "cache_key": f"fake-key-{len(self.calls)}",
            }

    pipeline = _make_pipeline(tmp_path)
    fake_tts = FakeTTSTool()
    pipeline.registry.register("tts", fake_tts)

    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="title",
                text="Title",
                segment_type="title_main",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="body",
                text="Body",
                segment_type="content",
                audio_request=AudioRequest(),
            ),
        ],
    )

    assets = pipeline._prepare_execution_assets(plan)

    assert len(fake_tts.calls) == 1
    assert fake_tts.calls[0]["text"] == "Body"
    assert [asset.segment_id for asset in assets.audio_assets] == ["body"]

def test_cli_plan_dispatch(monkeypatch):
    from md2video import cli

    monkeypatch.setattr(sys, "argv", [
        "md2video",
        "--plan",
        "plan.json",
        "-o",
        "artifacts/output.mp4",
    ])

    with patch("md2video.cli.Pipeline") as pipeline_cls:
        pipeline_cls.return_value.run_plan.return_value = Path("artifacts/output.mp4")
        cli.main()

    pipeline_cls.return_value.run_plan.assert_called_once_with(
        "plan.json",
        "artifacts/output.mp4",
    )
    assert not pipeline_cls.return_value.run.called
