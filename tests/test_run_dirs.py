"""A4 run 目录制：独立 run 目录、run_id 命名、失败标记、永不覆盖。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from md2video.inspect.runs import RUN_ID_PATTERN, create_run_dir, new_run_id
from md2video.manifest.schema import FinalResultManifest
from md2video.core.pipeline import Pipeline

from tests.test_pipeline_artifacts import (
    FakeRenderTool,
    _make_pipeline,
    _sole_run_dir,
    _write_stock_image_plan,
)


def _run_plan_once(tmp_path: Path, render_tool=None) -> tuple[Path, FinalResultManifest]:
    plan_path, _ = _write_stock_image_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    pipeline = _make_pipeline(tmp_path, render_tool=render_tool)
    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        pipeline.run_plan(str(plan_path), str(output_path))
    run_dir = _sole_run_dir(tmp_path)
    final_result = FinalResultManifest.model_validate_json(
        (run_dir / "result.json").read_text(encoding="utf-8"),
    )
    return run_dir, final_result


class TestRunId:
    def test_run_id_format_sortable_and_unique(self):
        now = datetime(2026, 9, 6, 12, 0, 0)
        first = new_run_id(now=now)
        second = new_run_id(now=now)
        assert RUN_ID_PATTERN.match(first)
        assert first.startswith("20260906-120000-")
        # 同秒内也全局唯一；时间戳前缀保证字典序可排序
        assert first != second
        later = new_run_id(now=datetime(2026, 9, 6, 12, 0, 1))
        assert first < later

    def test_create_run_dir_rejects_invalid_id(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid run id"):
            create_run_dir(tmp_path, "../escape")

    def test_create_run_dir_never_overwrites(self, tmp_path):
        run_id = new_run_id()
        first = create_run_dir(tmp_path, run_id)
        marker = first / "keep.txt"
        marker.write_text("data", encoding="utf-8")
        with pytest.raises(FileExistsError):
            create_run_dir(tmp_path, run_id)
        # 旧 run 目录内容原样保留
        assert marker.read_text(encoding="utf-8") == "data"


class TestPipelineRunDirs:
    def test_run_plan_creates_selfContained_run_dir(self, tmp_path):
        run_dir, final_result = _run_plan_once(tmp_path)

        assert run_dir.parent.name == "runs"
        assert RUN_ID_PATTERN.match(run_dir.name)
        assert final_result.run_id == run_dir.name
        assert final_result.status == "completed"

        # 四本账 + 检查页 + 渲染目录都落在本次 run 目录内
        for filename in (
            "plan.json",
            "execution-assets.json",
            "timeline.json",
            "result.json",
            "manifest_viewer.html",
        ):
            assert (run_dir / filename).is_file(), filename
        assert final_result.artifact_index["result"] == str(run_dir / "result.json")
        assert final_result.artifact_index["manifest_viewer"] == str(
            run_dir / "manifest_viewer.html"
        )

    def test_second_run_never_touches_first_run(self, tmp_path):
        plan_path, _ = _write_stock_image_plan(tmp_path)
        output_path = tmp_path / "output.mp4"

        first_pipeline = _make_pipeline(tmp_path)
        with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
            assembler_cls.return_value.assemble.return_value = output_path
            first_pipeline.run_plan(str(plan_path), str(output_path))
        first_run_dir = _sole_run_dir(tmp_path)
        first_result = (first_run_dir / "result.json").read_text(encoding="utf-8")

        second_pipeline = _make_pipeline(tmp_path)
        with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
            assembler_cls.return_value.assemble.return_value = output_path
            second_pipeline.run_plan(str(plan_path), str(output_path))

        runs = list((tmp_path / "runs").iterdir())
        assert len(runs) == 2
        assert first_run_dir in runs
        # 旧 run 的 result 原封不动；新 run 有自己的 run_id
        assert (first_run_dir / "result.json").read_text(encoding="utf-8") == first_result
        other_run_dir = next(r for r in runs if r != first_run_dir)
        second_result = FinalResultManifest.model_validate_json(
            (other_run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert second_result.run_id == other_run_dir.name
        assert second_result.run_id != first_pipeline.run_id

    def test_failed_run_marks_failed_result_and_keeps_previous_run(self, tmp_path):
        plan_path, _ = _write_stock_image_plan(tmp_path)
        output_path = tmp_path / "output.mp4"

        good_pipeline = _make_pipeline(tmp_path)
        with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
            assembler_cls.return_value.assemble.return_value = output_path
            good_pipeline.run_plan(str(plan_path), str(output_path))
        good_run_dir = _sole_run_dir(tmp_path)

        def failing_execute(input_data):
            raise RuntimeError("render exploded")

        failing = FakeRenderTool(tmp_path)
        failing.execute = failing_execute
        bad_pipeline = _make_pipeline(tmp_path, render_tool=failing)
        with pytest.raises(RuntimeError, match="render exploded"):
            bad_pipeline.run_plan(str(plan_path), str(output_path))

        runs = list((tmp_path / "runs").iterdir())
        assert len(runs) == 2
        assert good_run_dir in runs
        failed_run_dir = next(r for r in runs if r != good_run_dir)
        failed_result = FinalResultManifest.model_validate_json(
            (failed_run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert failed_result.status == "failed"
        assert failed_result.run_id == failed_run_dir.name
        assert failed_result.output_mp4 == ""
        assert any(
            "render exploded" in warning for warning in failed_result.warnings
        )
        # 失败 run 已写出的账本登记在案，且不会被误认成成功交付
        assert failed_result.artifact_index["plan"] == str(failed_run_dir / "plan.json")
        assert "manifest_viewer" not in failed_result.artifact_index

        # 旧 run 的 result.json 保持 completed，未受失败影响
        kept = FinalResultManifest.model_validate_json(
            (good_run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert kept.status == "completed"

    def test_unknown_style_pack_degrades_with_warning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MD2VIDEO_STYLE_PACK", "no_such_pack")
        run_dir, final_result = _run_plan_once(tmp_path)

        style_warning = [
            warning for warning in final_result.warnings
            if "no_such_pack" in warning and "ink_night" in warning
        ]
        assert style_warning, final_result.warnings

        # 检查页展示降级：请求名与解析名都进视图
        viewer_html = (run_dir / "manifest_viewer.html").read_text(encoding="utf-8")
        assert "no_such_pack" in viewer_html
        assert "ink_night" in viewer_html

    def test_render_warnings_are_collected_into_result(self, tmp_path):
        plan_path, _ = _write_stock_image_plan(tmp_path)
        output_path = tmp_path / "output.mp4"
        pipeline = _make_pipeline(tmp_path)
        render_tool = pipeline.registry.get_tool("render", "manim")
        original_execute = render_tool.execute

        def execute_with_warning(input_data):
            output = original_execute(input_data)
            return {**output, "warnings": ["Timeline warning: cue drifted"]}

        render_tool.execute = execute_with_warning

        with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
            assembler_cls.return_value.assemble.return_value = output_path
            pipeline.run_plan(str(plan_path), str(output_path))

        run_dir = _sole_run_dir(tmp_path)
        final_result = FinalResultManifest.model_validate_json(
            (run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert "Timeline warning: cue drifted" in final_result.warnings
