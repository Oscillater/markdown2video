"""ManimRenderTool tests."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from md2video.tools.protocol import Tool
from md2video.tools.render.manim_tool import ManimRenderTool


def _write_render_inputs(tmp_path: Path, plan_data=None) -> tuple[Path, Path, Path]:
    plan_path = tmp_path / "plan.json"
    assets_path = tmp_path / "execution-assets.json"
    timeline_path = tmp_path / "timeline.json"
    default_plan = {
        "version": "1",
        "segments": [{
            "id": "seg_001",
            "text": "hello",
            "segment_type": "content",
            "target_duration": 1.0,
        }],
        "scenes": [{
            "id": "scene_001",
            "shots": [{"id": "shot_001", "segment_ids": ["seg_001"]}],
        }],
    }
    plan_path.write_text(
        json.dumps(plan_data or default_plan),
        encoding="utf-8",
    )
    assets_path.write_text(
        '{"version":"1","audio_assets":[],"visual_assets":[]}',
        encoding="utf-8",
    )
    return plan_path, assets_path, timeline_path


def _write_timeline(timeline_path: Path, data=None) -> None:
    default_timeline = {
        "text": [{
            "segment_id": "seg_001",
            "segment_type": "content",
            "shot_id": "shot_001",
            "start": 0.0,
            "end": 1.0,
        }],
        "markers": [],
        "shots": [{
            "shot_id": "shot_001",
            "segment_ids": ["seg_001"],
            "start": 0.0,
            "end": 1.0,
        }],
    }
    timeline_path.write_text(
        json.dumps(data or default_timeline),
        encoding="utf-8",
    )


def _execute_with_rendered_timeline(tmp_path: Path, plan_data: dict, timeline_data: dict) -> dict:
    plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path, plan_data)
    tool = ManimRenderTool()
    completed = MagicMock(returncode=0, stderr="")

    def run_success(*args, **kwargs):
        _write_timeline(Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]), timeline_data)
        return completed

    with patch(
        "md2video.tools.render.manim_tool.subprocess.run",
        side_effect=run_success,
    ):
        with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
            return tool.execute({
                "plan_path": str(plan_path),
                "execution_assets_path": str(assets_path),
                "timeline_path": str(timeline_path),
                "output_dir": str(tmp_path),
            })


def _title_only_plan(segment_id: str, segment_type: str) -> dict:
    return {
        "version": "1",
        "segments": [{
            "id": segment_id,
            "text": "Title",
            "segment_type": segment_type,
        }],
        "scenes": [{
            "id": "scene_title",
            "shots": [{
                "id": "shot_title",
                "segment_ids": [segment_id],
            }],
        }],
    }


def _title_only_timeline(segment_id: str, segment_type: str) -> dict:
    return {
        "text": [{
            "segment_id": segment_id,
            "segment_type": segment_type,
            "scene_id": "scene_title",
            "shot_id": "shot_title",
            "text": "Title",
            "start": 0.0,
            "end": 2.0,
        }],
        "markers": [],
        "shots": [{
            "shot_id": "shot_title",
            "segment_ids": [segment_id],
            "start": 0.0,
            "end": 2.0,
        }],
    }


def _marker_plan() -> dict:
    return {
        "version": "1",
        "segments": [],
        "scenes": [{
            "id": "scene_001",
            "shots": [{
                "id": "shot_001",
                "segment_ids": [],
                "cues": [{
                    "id": "marker_001",
                    "cue_type": "marker_music",
                    "kind": "start",
                    "name": "bgm",
                }],
            }],
        }],
    }


def _marker_timeline(marker: dict | None) -> dict:
    return {
        "text": [],
        "markers": [] if marker is None else [marker],
        "shots": [{
            "shot_id": "shot_001",
            "segment_ids": [],
            "start": 1.0,
            "end": 1.0,
        }],
    }


class TestManimRenderTool:
    def test_tool_type(self):
        tool = ManimRenderTool()
        assert tool.tool_type == "render"

    def test_provider_name(self):
        tool = ManimRenderTool()
        assert tool.provider_name == "manim"

    def test_satisfies_tool_protocol(self):
        tool = ManimRenderTool()
        assert isinstance(tool, Tool)

    def test_execute_uses_isolated_workdir_and_explicit_env(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path)
        output_dir = tmp_path / "renders"
        completed = MagicMock(returncode=0, stderr="")
        tool = ManimRenderTool()

        def run_success(*args, **kwargs):
            _write_timeline(Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]))
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ) as run:
            with patch.object(
                tool,
                "_find_rendered_video",
                return_value=tmp_path / "rendered.mp4",
            ) as find_rendered:
                output = tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(output_dir),
                    "timeout": 123,
                })

        assert output["video_path"] == str(tmp_path / "rendered.mp4")
        assert output["timeline_path"] == str(timeline_path)
        assert output["provider"] == "manim"
        assert Path(output["render_dir"]).parent == output_dir

        render_cwd = Path(run.call_args.kwargs["cwd"])
        assert render_cwd.parent == output_dir
        find_rendered.assert_called_once_with(render_cwd)

        cmd = run.call_args.args[0]
        assert cmd[:4] == [sys.executable, "-m", "manim", "render"]
        # 分辨率来自 manim.cfg（竖屏 480x854），不允许质量旗标覆盖成 16:9
        assert "-ql" not in cmd
        assert "manifest_scene.py" in cmd
        assert run.call_args.kwargs["timeout"] == 123

        env = run.call_args.kwargs["env"]
        assert env["MD2VIDEO_PLAN_PATH"] == str(plan_path.resolve())
        assert env["MD2VIDEO_EXECUTION_ASSETS_PATH"] == str(assets_path.resolve())
        assert env["MD2VIDEO_TIMELINE_PATH"] == str(timeline_path.resolve())
        assert "MD2VIDEO_ARTIFACTS_DIR" not in env

    def test_execute_fails_when_required_input_missing(self, tmp_path):
        tool = ManimRenderTool()
        with pytest.raises(ValueError, match="execution_assets_path"):
            tool.execute({
                "plan_path": str(tmp_path / "plan.json"),
                "timeline_path": str(tmp_path / "timeline.json"),
            })

    def test_execute_fails_when_plan_missing(self, tmp_path):
        _, assets_path, timeline_path = _write_render_inputs(tmp_path)
        tool = ManimRenderTool()
        with pytest.raises(FileNotFoundError, match="Plan manifest not found"):
            tool.execute({
                "plan_path": str(tmp_path / "missing-plan.json"),
                "execution_assets_path": str(assets_path),
                "timeline_path": str(timeline_path),
                "output_dir": str(tmp_path),
            })

    def test_execute_rejects_unknown_shot_segment_before_manim(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001", "missing_segment"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()

        with patch("md2video.tools.render.manim_tool.subprocess.run") as run:
            with pytest.raises(ValueError, match="missing_segment"):
                tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(tmp_path),
                })

        run.assert_not_called()

    def test_execute_rejects_missing_audio_asset_before_manim(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                    "audio_request": {},
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()

        with patch("md2video.tools.render.manim_tool.subprocess.run") as run:
            with pytest.raises(ValueError, match="missing audio assets.*seg_001"):
                tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(tmp_path),
                })

        run.assert_not_called()

    def test_execute_raises_runtime_error_on_manim_failure(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path)
        tool = ManimRenderTool()
        completed = MagicMock(returncode=2, stderr="line1\nline2")

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            return_value=completed,
        ):
            with pytest.raises(RuntimeError, match="Manim rendering failed"):
                tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(tmp_path),
                })

    def test_execute_raises_when_no_video_found(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path)
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]))
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=None):
                with pytest.raises(FileNotFoundError, match="No rendered video found"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

    def test_execute_removes_stale_timeline_and_requires_new_one(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path)
        _write_timeline(timeline_path, {"text": [{"old": True}], "markers": [], "shots": []})
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            return_value=completed,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(FileNotFoundError, match="Timeline not generated"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

        assert not timeline_path.exists()

    def test_execute_rejects_invalid_timeline_shape(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(tmp_path)
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]), {"text": []})
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(RuntimeError, match="Timeline missing required keys"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

    def test_execute_rejects_timeline_missing_plan_shot(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(
                Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]),
                {"text": [], "markers": [], "shots": []},
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(RuntimeError, match="Timeline missing plan shots.*shot_001"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

    def test_execute_rejects_timeline_missing_plan_segment(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(
                Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]),
                {
                    "text": [],
                    "markers": [],
                    "shots": [{
                        "shot_id": "shot_001",
                        "segment_ids": [],
                        "start": 0.0,
                        "end": 1.0,
                    }],
                },
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(
                    RuntimeError,
                    match="Timeline missing plan segments.*shot_001.*seg_001",
                ):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

    def test_execute_accepts_marker_cue_only_shot_timeline(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": [],
                        "cues": [{
                            "id": "marker_001",
                            "cue_type": "marker_music",
                            "kind": "start",
                            "name": "bgm",
                        }],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(
                Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]),
                {
                    "text": [],
                    "markers": [{
                        "id": "marker_001",
                        "cue_type": "marker_music",
                        "shot_id": "shot_001",
                        "time": 1.0,
                    }],
                    "shots": [{
                        "shot_id": "shot_001",
                        "segment_ids": [],
                        "start": 1.0,
                        "end": 1.0,
                    }],
                },
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                output = tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(tmp_path),
                })

        assert output["timeline_path"] == str(timeline_path)

    @pytest.mark.parametrize(
        ("segment_id", "segment_type"),
        [
            ("title_001", "title_main"),
            ("subtitle_001", "title_sub"),
        ],
    )
    def test_execute_accepts_single_title_shot_timeline(self, tmp_path, segment_id, segment_type):
        output = _execute_with_rendered_timeline(
            tmp_path,
            _title_only_plan(segment_id, segment_type),
            _title_only_timeline(segment_id, segment_type),
        )

        assert output["timeline_path"] == str(tmp_path / "timeline.json")

    def test_execute_accepts_mixed_title_body_shot_timeline(self, tmp_path):
        output = _execute_with_rendered_timeline(
            tmp_path,
            {
                "version": "1",
                "segments": [
                    {
                        "id": "title_001",
                        "text": "Title",
                        "segment_type": "title_main",
                    },
                    {
                        "id": "seg_001",
                        "text": "Body",
                        "segment_type": "content",
                        "target_duration": 1.0,
                    },
                ],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["title_001", "seg_001"],
                    }],
                }],
            },
            {
                "text": [
                    {
                        "segment_id": "title_001",
                        "segment_type": "title_main",
                        "scene_id": "scene_001",
                        "shot_id": "shot_001",
                        "start": 0.0,
                        "end": 2.0,
                    },
                    {
                        "segment_id": "seg_001",
                        "segment_type": "content",
                        "scene_id": "scene_001",
                        "shot_id": "shot_001",
                        "start": 2.0,
                        "end": 3.0,
                    },
                ],
                "markers": [],
                "shots": [{
                    "shot_id": "shot_001",
                    "scene_id": "scene_001",
                    "segment_ids": ["title_001", "seg_001"],
                    "start": 0.0,
                    "end": 3.0,
                }],
            },
        )

        assert output["timeline_path"] == str(tmp_path / "timeline.json")

    def test_execute_rejects_marker_cue_missing_timeline_marker(self, tmp_path):
        with pytest.raises(RuntimeError, match="Timeline missing marker entries.*marker_001"):
            _execute_with_rendered_timeline(
                tmp_path,
                _marker_plan(),
                _marker_timeline(marker=None),
            )

    @pytest.mark.parametrize(
        "marker",
        [
            {"segment_id": "marker_001"},
            {"segment_id": "marker_001", "time": "not-a-number"},
            {"segment_id": "marker_001", "time": math.inf},
        ],
    )
    def test_execute_rejects_marker_timeline_invalid_time(self, tmp_path, marker):
        with pytest.raises(RuntimeError, match="Timeline marker time.*marker_001"):
            _execute_with_rendered_timeline(
                tmp_path,
                _marker_plan(),
                _marker_timeline(marker),
            )

    def test_execute_rejects_timeline_shot_missing_timing(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(
                Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]),
                {
                    "text": [],
                    "markers": [],
                    "shots": [{
                        "shot_id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                },
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(RuntimeError, match="Timeline shot missing start/end.*shot_001"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })

    def test_execute_rejects_timeline_shot_end_before_start(self, tmp_path):
        plan_path, assets_path, timeline_path = _write_render_inputs(
            tmp_path,
            {
                "version": "1",
                "segments": [{
                    "id": "seg_001",
                    "text": "hello",
                    "segment_type": "content",
                }],
                "scenes": [{
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": ["seg_001"],
                    }],
                }],
            },
        )
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            _write_timeline(
                Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]),
                {
                    "text": [],
                    "markers": [],
                    "shots": [{
                        "shot_id": "shot_001",
                        "segment_ids": ["seg_001"],
                        "start": 2.0,
                        "end": 1.0,
                    }],
                },
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(tool, "_find_rendered_video", return_value=tmp_path / "rendered.mp4"):
                with pytest.raises(RuntimeError, match="Timeline shot end before start.*shot_001"):
                    tool.execute({
                        "plan_path": str(plan_path),
                        "execution_assets_path": str(assets_path),
                        "timeline_path": str(timeline_path),
                        "output_dir": str(tmp_path),
                    })
