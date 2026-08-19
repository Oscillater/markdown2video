from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

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


def _make_pipeline(tmp_path, voice=None, speed=None):
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
                "target_duration": 2.0,
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
    pipeline._render_manim_batch = MagicMock(
        return_value=(tmp_path / "base.mp4", tmp_path / "timeline.json"),
    )

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        result = pipeline.run_plan(str(plan_path), str(output_path))

    assert result == output_path
    pipeline._render_manim_batch.assert_called_once_with(tmp_path)

    assets_path = tmp_path / "execution-assets.json"
    assets = ExecutionAssets.model_validate_json(assets_path.read_text(encoding="utf-8"))
    assert len(assets.audio_assets) == 0
    assert len(assets.visual_assets) == 1
    assert assets.visual_assets[0].shot_id == "shot_001"
    assert assets.visual_assets[0].provider == "local"
    assert assets.visual_assets[0].path == str(image_path.resolve())

    assembler_cls.assert_called_once()
    assert assembler_cls.call_args.kwargs["execution_assets"].visual_assets[0].provider == "local"

    final_result = FinalResultManifest.model_validate_json(
        (tmp_path / "result.json").read_text(encoding="utf-8"),
    )
    assert final_result.output_mp4 == str(output_path)
    assert final_result.artifact_index["execution_assets"] == str(assets_path)
    assert final_result.used_assets["visual"][0]["shot_id"] == "shot_001"

    raw_result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert "segments" not in raw_result


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


def test_render_manim_batch_uses_isolated_workdir(tmp_path):
    pipeline = _make_pipeline(tmp_path)
    root_manifest_scene = tmp_path / "manifest_scene.py"
    root_manim_cfg = tmp_path / "manim.cfg"
    root_manifest_scene.write_text("caller scene", encoding="utf-8")
    root_manim_cfg.write_text("caller cfg", encoding="utf-8")

    completed = MagicMock(returncode=0, stderr="")
    with patch("md2video.core.pipeline.subprocess.run", return_value=completed) as run:
        with patch.object(
            pipeline,
            "_find_rendered_video",
            return_value=tmp_path / "rendered.mp4",
        ) as find_rendered:
            video_path, timeline_path = pipeline._render_manim_batch(tmp_path)

    assert video_path == tmp_path / "rendered.mp4"
    assert timeline_path == tmp_path / "timeline.json"
    assert root_manifest_scene.read_text(encoding="utf-8") == "caller scene"
    assert root_manim_cfg.read_text(encoding="utf-8") == "caller cfg"

    render_cwd = Path(run.call_args.kwargs["cwd"])
    assert render_cwd != tmp_path
    assert render_cwd.parent == tmp_path
    find_rendered.assert_called_once_with(render_cwd)


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
