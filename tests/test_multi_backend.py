"""A6 前半：按 scene 多后端分发与合成基础设施（fake backend 验收）。"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from md2video.config import ToolConfig
from md2video.core.multi_backend import (
    RenderGroup,
    check_merged_timeline,
    concat_group_videos,
    effective_backend,
    merge_group_timelines,
    plan_render_groups,
    slice_plan,
)
from md2video.core.pipeline import Pipeline
from md2video.manifest.schema import (
    AudioAsset,
    ExecutionAssets,
    FinalResultManifest,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    ShotPlan,
)
from md2video.tools.render.manim_renderer_inputs import validate_renderer_inputs


WIDTH, HEIGHT, FPS = 480, 854, 30

RENDER_SMOKE_ENV = "MD2VIDEO_RENDER_SMOKE"


def _requires_real_render(test):
    return pytest.mark.skipif(
        os.environ.get(RENDER_SMOKE_ENV) != "1",
        reason=f"set {RENDER_SMOKE_ENV}=1 to run the real manim render test",
    )(test)


class FakeSliceRenderTool:
    """合同保真的假渲染后端：校验切片输入，产出局部 timeline + 真实 mp4。

    timeline 从切片 plan 合成（每 shot 固定秒数、顺序排布），mp4 用
    ffmpeg 纯色源生成并带静音轨，使其可与 manim 底片走同一条 concat 路径。
    """

    tool_type = "render"

    def __init__(self, provider_name: str, color: str = "dimgray",
                 shot_seconds: float = 1.0):
        self.provider_name = provider_name
        self.color = color
        self.shot_seconds = shot_seconds
        self.calls: list[dict] = []

    def execute(self, input_data: dict) -> dict:
        self.calls.append(input_data)
        plan = PlanManifest.model_validate_json(
            Path(input_data["plan_path"]).read_text(encoding="utf-8"),
        )
        assets = ExecutionAssets.model_validate_json(
            Path(input_data["execution_assets_path"]).read_text(encoding="utf-8"),
        )
        # 真实后端的合同义务：切片输入先过渲染输入校验
        validate_renderer_inputs(plan, assets)

        timeline_path = Path(input_data["timeline_path"])
        output_dir = Path(input_data["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        timeline_path.parent.mkdir(parents=True, exist_ok=True)

        shots = []
        text = []
        markers = []
        t = 0.0
        for scene in plan.scenes:
            for shot in scene.shots:
                start, end = t, t + self.shot_seconds
                shots.append({
                    "shot_id": shot.id,
                    "scene_id": scene.id,
                    "layout_type": scene.layout_type,
                    "start": start,
                    "end": end,
                    "segment_ids": list(shot.segment_ids),
                })
                for sid in shot.segment_ids:
                    segment = next(s for s in plan.segments if s.id == sid)
                    text.append({
                        "segment_id": sid,
                        "segment_type": segment.segment_type,
                        "text": segment.text,
                        "start": start,
                        "end": end,
                        "scene_id": scene.id,
                        "shot_id": shot.id,
                    })
                for cue in shot.cues:
                    markers.append({
                        "id": cue.get("id", ""),
                        "cue_type": cue.get("cue_type", ""),
                        "kind": cue.get("kind", ""),
                        "name": cue.get("name", ""),
                        "time": start,
                        "scene_id": scene.id,
                        "shot_id": shot.id,
                    })
                t = end

        timeline = {"text": text, "markers": markers, "shots": shots}
        timeline_path.write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8",
        )

        duration = t
        video_path = output_dir / f"{self.provider_name}_base.mp4"
        # 无音轨底片：与静音 manim 渲染同构，concat/assembler 按无音轨处理
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c={self.color}:s={WIDTH}x{HEIGHT}:r={FPS}",
                "-t", f"{duration:.6f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(video_path),
            ],
            check=True, capture_output=True,
        )
        render_dir = output_dir / "fake_render"
        render_dir.mkdir(parents=True, exist_ok=True)
        return {
            "video_path": str(video_path),
            "timeline_path": str(timeline_path),
            "provider": self.provider_name,
            "render_dir": str(render_dir),
        }


def _make_pipeline(tmp_path: Path, *render_tools) -> Pipeline:
    with patch.object(Pipeline, "_create_planner"), \
            patch.object(Pipeline, "_register_default_tools"):
        pipeline = Pipeline(
            artifacts_dir=tmp_path,
            tool_config=ToolConfig(priority={"stock_image": ["local"]}),
        )
    from md2video.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in render_tools:
        registry.register("render", tool)
    pipeline.registry = registry
    return pipeline


def _mixed_plan() -> PlanManifest:
    """三组：manim 兼容 fake（组0）→ fake-backend x2 scene（组1）→ manim 兼容 fake（组2）。"""
    segments = [
        SegmentPlan(id="seg_001", text="第一组", segment_type="content"),
        SegmentPlan(id="seg_002", text="第二组甲", segment_type="content"),
        SegmentPlan(id="seg_003", text="第二组乙", segment_type="content"),
        SegmentPlan(id="seg_004", text="第三组", segment_type="content"),
    ]
    return PlanManifest(
        segments=segments,
        scenes=[
            ScenePlan(id="scene_001", shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])]),
            ScenePlan(
                id="scene_002", render_backend="fake-backend",
                shots=[ShotPlan(id="shot_002", segment_ids=["seg_002"])],
            ),
            ScenePlan(
                id="scene_003", render_backend="fake-backend",
                shots=[ShotPlan(
                    id="shot_003", segment_ids=["seg_003"],
                    cues=[{"id": "cue_ping", "cue_type": "marker_music",
                           "kind": "start", "name": "bgm", "position": "start"}],
                )],
            ),
            ScenePlan(id="scene_004", shots=[ShotPlan(id="shot_004", segment_ids=["seg_004"])]),
        ],
    )


def _sole_run_dir(tmp_path: Path) -> Path:
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    return runs[0]


class TestGrouping:
    def test_adjacent_same_backend_scenes_form_maximal_groups(self):
        plan = _mixed_plan()
        groups = plan_render_groups(plan, "manim")
        assert [(g.backend, [s.id for s in g.scenes]) for g in groups] == [
            ("manim", ["scene_001"]),
            ("fake-backend", ["scene_002", "scene_003"]),
            ("manim", ["scene_004"]),
        ]

    def test_empty_scene_backend_falls_back_to_config(self):
        scene = ScenePlan(id="s")
        assert effective_backend(scene, "manim") == "manim"
        assert effective_backend(scene, "remotion") == "remotion"
        assert effective_backend(ScenePlan(id="s", render_backend="x"), "manim") == "x"

    def test_single_backend_plan_is_one_group(self):
        plan = PlanManifest(scenes=[ScenePlan(id="a"), ScenePlan(id="b")])
        groups = plan_render_groups(plan, "manim")
        assert len(groups) == 1
        assert groups[0].backend == "manim"
        assert [s.id for s in groups[0].scenes] == ["a", "b"]


class TestSliceAndMerge:
    def test_slice_plan_keeps_only_referenced_segments(self):
        plan = PlanManifest(
            segments=[
                SegmentPlan(id="used", text="u", segment_type="content"),
                SegmentPlan(id="unused", text="n", segment_type="content"),
            ],
            scenes=[ScenePlan(id="s", shots=[ShotPlan(id="sh", segment_ids=["used"])])],
            media_declarations={"music": {"bgm": "./m.mp3"}},
        )
        slice = slice_plan(plan, plan.scenes)
        assert [s.id for s in slice.segments] == ["used"]
        assert slice.media_declarations == {"music": {"bgm": "./m.mp3"}}
        # 切片是合法渲染输入：全部可渲染 segment 都被 shot 覆盖
        validate_renderer_inputs(slice, ExecutionAssets())

    def test_merge_prefix_offsets_groups(self):
        local_a = {
            "text": [{"segment_id": "a", "start": 0.0, "end": 2.0}],
            "markers": [{"id": "m1", "time": 1.0}],
            "shots": [
                {"shot_id": "s1", "start": 0.0, "end": 1.0, "segment_ids": ["a"]},
                {"shot_id": "s2", "start": 1.0, "end": 2.5, "segment_ids": ["b"]},
            ],
        }
        local_b = {
            "text": [{"segment_id": "c", "start": 0.0, "end": 1.0}],
            "markers": [{"id": "m2", "time": 0.5}],
            "shots": [{"shot_id": "s3", "start": 0.0, "end": 1.0, "segment_ids": ["c"]}],
        }
        merged = merge_group_timelines([local_a, local_b])
        # 组时长 = 组内末 shot end；第二组整体偏移 2.5
        assert merged["shots"][2]["start"] == pytest.approx(2.5)
        assert merged["shots"][2]["end"] == pytest.approx(3.5)
        assert merged["text"][1]["start"] == pytest.approx(2.5)
        assert merged["markers"][1]["time"] == pytest.approx(3.0)
        # 原局部数据不被就地修改
        assert local_b["shots"][0]["start"] == 0.0

    def test_merged_timeline_passes_global_gate_against_full_plan(self):
        plan = _mixed_plan()
        assets = ExecutionAssets()
        local = {
            "text": [
                {"segment_id": s.id, "segment_type": s.segment_type, "text": s.text,
                 "start": i * 1.0, "end": (i + 1) * 1.0,
                 "shot_id": f"shot_{i + 1:03d}"}
                for i, s in enumerate(plan.segments)
            ],
            "markers": [{"id": "cue_ping", "time": 2.0, "shot_id": "shot_003"}],
            "shots": [
                {"shot_id": f"shot_{i + 1:03d}", "scene_id": f"scene_{i + 1:03d}",
                 "start": i * 1.0, "end": (i + 1) * 1.0,
                 "segment_ids": [s.id]}
                for i, s in enumerate(plan.segments)
            ],
        }
        merged = merge_group_timelines([local])
        check_merged_timeline(plan, assets, merged)  # 不抛即过

    def test_merged_timeline_gate_rejects_missing_shots(self):
        plan = _mixed_plan()
        bad_merged = {"text": [], "markers": [], "shots": []}
        with pytest.raises(RuntimeError, match="Merged timeline failed global invariants"):
            check_merged_timeline(plan, ExecutionAssets(), bad_merged)


class TestConcat:
    def _render_color(self, path: Path, color: str, seconds: float, with_audio: bool):
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}",
        ]
        if with_audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
        cmd += ["-t", f"{seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if with_audio:
            cmd += ["-c:a", "aac"]
        cmd.append(str(path))
        subprocess.run(cmd, check=True, capture_output=True)

    def _probe_duration(self, path: Path) -> float:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
        return float(proc.stdout.strip())

    def test_concat_mixed_audio_groups_fills_silence(self, tmp_path):
        silent = tmp_path / "silent.mp4"
        voiced = tmp_path / "voiced.mp4"
        self._render_color(silent, "red", 1.0, with_audio=False)
        self._render_color(voiced, "blue", 1.5, with_audio=True)

        out = concat_group_videos([silent, voiced], tmp_path / "concat.mp4")
        assert self._probe_duration(out) == pytest.approx(2.5, abs=0.2)

    def test_concat_all_silent_groups_yields_no_audio_track(self, tmp_path):
        first = tmp_path / "a.mp4"
        second = tmp_path / "b.mp4"
        self._render_color(first, "red", 1.0, with_audio=False)
        self._render_color(second, "blue", 1.5, with_audio=False)

        out = concat_group_videos([first, second], tmp_path / "concat.mp4")
        assert self._probe_duration(out) == pytest.approx(2.5, abs=0.2)
        # 全静音 run 出无音轨底片，交给 assembler 走已验证的 anullsrc 路径
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True,
        )
        assert proc.stdout.strip() == ""

    def test_concat_requires_multiple_videos(self, tmp_path):
        with pytest.raises(ValueError, match="Single group"):
            concat_group_videos([tmp_path / "a.mp4"], tmp_path / "out.mp4")


class TestPipelineMultiBackend:
    def test_mixed_plan_renders_one_video_and_passes_all_gates(self, tmp_path):
        """混合后端 plan：分组切片 → 合并 timeline 过全局闸门 → 拼接 → 成片。"""
        plan_path = tmp_path / "mixed_plan.json"
        plan = _mixed_plan()
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        output_path = tmp_path / "mixed_output.mp4"

        group_tool = FakeSliceRenderTool("fake-backend", color="blue")
        manim_like = FakeSliceRenderTool("manim", color="dimgray")
        pipeline = _make_pipeline(tmp_path, manim_like, group_tool)

        result = pipeline.run_plan(str(plan_path), str(output_path))
        assert result == output_path
        assert output_path.is_file()

        run_dir = _sole_run_dir(tmp_path)
        # 每组一个目录，各组各自从 t=0 渲自己的切片（两次 manim 组调用）
        assert len(manim_like.calls) == 2
        assert len(group_tool.calls) == 1
        for index, backend in ((0, "manim"), (1, "fake-backend"), (2, "manim")):
            group_dir = run_dir / "groups" / f"{index:02d}_{backend}"
            assert (group_dir / "plan.json").is_file()
            assert (group_dir / "timeline.json").is_file()
        # 组切片只含自己引用的 segment
        slice_1 = json.loads(
            (run_dir / "groups" / "01_fake-backend" / "plan.json").read_text(encoding="utf-8"),
        )
        assert [s["id"] for s in slice_1["segments"]] == ["seg_002", "seg_003"]

        # 合并 timeline 是主 timeline，shot 时序经前缀偏移、全局闸门已过
        merged = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
        shot_ends = {s["shot_id"]: s["end"] for s in merged["shots"]}
        assert shot_ends["shot_001"] == pytest.approx(1.0)
        assert shot_ends["shot_002"] == pytest.approx(2.0)
        assert shot_ends["shot_004"] == pytest.approx(4.0)

        final_result = FinalResultManifest.model_validate_json(
            (run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert final_result.status == "completed"
        assert final_result.artifact_index["render_provider"] == "manim+fake-backend+manim"
        assert final_result.artifact_index["base_video"] == str(run_dir / "base_video.mp4")

    def test_unregistered_scene_backend_fails_fast_before_render(self, tmp_path):
        plan = PlanManifest(
            segments=[SegmentPlan(id="seg_001", text="x", segment_type="content")],
            scenes=[ScenePlan(
                id="scene_001", render_backend="remotion",
                shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])],
            )],
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        output_path = tmp_path / "out.mp4"

        group_tool = FakeSliceRenderTool("fake-backend")
        pipeline = _make_pipeline(tmp_path, group_tool)
        with pytest.raises(ValueError, match="Render tool not registered: render/remotion"):
            pipeline.run_plan(str(plan_path), str(output_path))
        # 开渲前 fail fast：任何后端都没被调用
        assert group_tool.calls == []

    def test_single_scene_backend_switches_whole_run(self, tmp_path):
        """单组但后端非默认：整条 run 走该后端，行为与单后端路径一致。"""
        plan = PlanManifest(
            segments=[SegmentPlan(id="seg_001", text="x", segment_type="content")],
            scenes=[ScenePlan(
                id="scene_001", render_backend="fake-backend",
                shots=[ShotPlan(id="shot_001", segment_ids=["seg_001"])],
            )],
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        output_path = tmp_path / "out.mp4"

        # 合成器的 loudnorm 需 >=3s 音频才开始输出（assembler 既有特性），
        # 片子做到 4s 避开这个与多后端无关的下限
        group_tool = FakeSliceRenderTool("fake-backend", shot_seconds=4.0)
        pipeline = _make_pipeline(tmp_path, group_tool)
        pipeline.run_plan(str(plan_path), str(output_path))

        run_dir = _sole_run_dir(tmp_path)
        assert len(group_tool.calls) == 1
        # 单组路径不经过 groups/ 子目录，timeline 直接在 run 目录
        call = group_tool.calls[0]
        assert call["timeline_path"] == str(run_dir / "timeline.json")
        assert call["output_dir"] == str(run_dir)
        assert not (run_dir / "groups").exists()

    def test_merged_timeline_gate_failure_aborts_run(self, tmp_path):
        """合并后的 timeline 过不了全局闸门 → run 失败并标记 failed。"""
        plan_path = tmp_path / "plan.json"
        plan = _mixed_plan()
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        output_path = tmp_path / "out.mp4"

        group_tool = FakeSliceRenderTool("fake-backend")

        class TimelineDropper(FakeSliceRenderTool):
            """第二个组产出缺 shot 的坏 timeline，模拟后端违约。"""

            def execute(self, input_data):
                output = super().execute(input_data)
                timeline = json.loads(Path(output["timeline_path"]).read_text(encoding="utf-8"))
                timeline["shots"] = []
                Path(output["timeline_path"]).write_text(
                    json.dumps(timeline), encoding="utf-8",
                )
                return output

        dropper = TimelineDropper("dropper-backend", color="green")
        manim_like = FakeSliceRenderTool("manim")
        pipeline = _make_pipeline(tmp_path, manim_like, group_tool, dropper)

        plan.scenes[1].render_backend = "dropper-backend"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        with pytest.raises(RuntimeError, match="Merged timeline failed global invariants"):
            pipeline.run_plan(str(plan_path), str(output_path))

        run_dir = _sole_run_dir(tmp_path)
        failed = FinalResultManifest.model_validate_json(
            (run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert failed.status == "failed"


@_requires_real_render
class TestRealManimMixedWithFake:
    """验收：混合 manim/fake 的 plan 出一条成片且过全部闸门。"""

    def test_manim_group_then_fake_group_single_output(self, tmp_path):
        from md2video.tools.render.manim_tool import ManimRenderTool

        plan = PlanManifest(
            segments=[
                SegmentPlan(id="title_main_001", text="混合引擎", segment_type="title_main"),
                SegmentPlan(id="content_001", text="manim 组渲染这段", segment_type="content"),
                SegmentPlan(id="content_002", text="fake 组渲染这段", segment_type="content"),
            ],
            scenes=[
                ScenePlan(id="scene_001", shots=[ShotPlan(id="shot_001", segment_ids=["title_main_001"])]),
                ScenePlan(id="scene_002", shots=[ShotPlan(id="shot_002", segment_ids=["content_001"])]),
                ScenePlan(
                    id="scene_003", render_backend="fake-backend",
                    shots=[ShotPlan(id="shot_003", segment_ids=["content_002"])],
                ),
            ],
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        output_path = tmp_path / "mixed_final.mp4"

        pipeline = _make_pipeline(tmp_path, ManimRenderTool(), FakeSliceRenderTool("fake-backend", color="blue"))
        result = pipeline.run_plan(str(plan_path), str(output_path))

        assert result == output_path
        assert output_path.is_file()

        run_dir = _sole_run_dir(tmp_path)
        # 两组目录：真 manim 组 + fake 组；fake 组从 t=0 渲自己的切片
        assert (run_dir / "groups" / "00_manim" / "timeline.json").is_file()
        assert (run_dir / "groups" / "01_fake-backend" / "timeline.json").is_file()
        fake_local = json.loads(
            (run_dir / "groups" / "01_fake-backend" / "timeline.json").read_text(encoding="utf-8"),
        )
        assert fake_local["shots"][0]["start"] == pytest.approx(0.0)

        # 合并 timeline：fake 组 shot 的起点 = manim 组末 shot 的终点（组边界清零）
        merged = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
        ends = {s["shot_id"]: s["end"] for s in merged["shots"]}
        starts = {s["shot_id"]: s["start"] for s in merged["shots"]}
        assert starts["shot_003"] == pytest.approx(ends["shot_002"])
        assert ends["shot_003"] > ends["shot_002"]

        # 合并 timeline 已过全局闸门；成片规格与现有 assembler 输出一致
        check_merged_timeline(plan, ExecutionAssets(), merged)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(output_path)],
            capture_output=True, text=True,
        )
        assert probe.stdout.strip() == f"{WIDTH}x{HEIGHT}"

        final_result = FinalResultManifest.model_validate_json(
            (run_dir / "result.json").read_text(encoding="utf-8"),
        )
        assert final_result.status == "completed"
        assert final_result.artifact_index["render_provider"] == "manim+fake-backend"
