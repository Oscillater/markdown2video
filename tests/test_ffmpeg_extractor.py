"""Tests for extract_music_entries, extract_image_entries and extract_shot_visual_entries in ffmpeg_assembler."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import md2video.assembler.ffmpeg_assembler as ffmpeg_assembler
from md2video.assembler.ffmpeg_assembler import (
    attach_image_layout_regions,
    build_and_run_ffmpeg,
    extract_image_entries,
    extract_music_entries,
    extract_shot_visual_entries,
    extract_shot_visual_entries_from_assets,
)
from md2video.config import KenBurnsConfig
from md2video.manifest.schema import (
    AudioResult,
    ExecutionAssets,
    PlanManifest,
    ResultManifest,
    SceneResult,
    SegmentPlan,
    SegmentResult,
    ScenePlan,
    ShotPlan,
    ShotResult,
    VisualAsset,
    VisualResult,
)


def _make_plan(segments, media_declarations=None):
    return PlanManifest(segments=segments, media_declarations=media_declarations or {})


def _make_result(segment_results):
    return ResultManifest(segments=segment_results)


def _cue(cue_id, cue_type, kind, name):
    return {
        "id": cue_id,
        "cue_type": cue_type,
        "kind": kind,
        "name": name,
    }


def _plan_with_cues(cues, media_declarations=None):
    return PlanManifest(
        segments=[],
        scenes=[
            ScenePlan(
                id="scene_001",
                shots=[ShotPlan(id="shot_001", cues=cues)],
            ),
        ],
        media_declarations=media_declarations or {},
    )


def _write_marker_timeline(tmp_path, markers):
    path = tmp_path / "timeline.json"
    path.write_text(
        json.dumps({"text": [], "markers": markers, "shots": []}),
        encoding="utf-8",
    )
    return path


class TestExtractMusicEntries:
    def test_basic_start_end(self, tmp_path):
        plan = _plan_with_cues(
            [
                _cue("m1", "marker_music", "start", "bgm"),
                _cue("m2", "marker_music", "end", "bgm"),
            ],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        timeline_path = _write_marker_timeline(
            tmp_path,
            [{"id": "m1", "time": 4.0}, {"id": "m2", "time": 6.0}],
        )
        entries = extract_music_entries(plan, _make_result([]), timeline_path)
        assert len(entries) == 1
        assert entries[0]["name"] == "bgm"
        assert entries[0]["src"] == "./music.mp3"
        assert entries[0]["start"] == 4.0
        assert entries[0]["end"] == 6.0

    def test_missing_src(self, tmp_path):
        plan = _plan_with_cues([_cue("m1", "marker_music", "start", "unknown")])
        timeline_path = _write_marker_timeline(tmp_path, [{"id": "m1", "time": 0.0}])
        entries = extract_music_entries(plan, _make_result([]), timeline_path)
        assert len(entries) == 1
        assert entries[0]["src"] is None

    def test_missing_timeline_marker_fails_fast(self):
        plan = _plan_with_cues(
            [_cue("m1", "marker_music", "start", "bgm")],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        try:
            extract_music_entries(plan, _make_result([]))
        except ValueError as exc:
            assert "m1" in str(exc)
        else:
            raise AssertionError("missing marker timeline should fail fast")

    def test_multiple_pairs(self, tmp_path):
        plan = _plan_with_cues(
            [
                _cue("m1", "marker_music", "start", "a"),
                _cue("m2", "marker_music", "end", "a"),
                _cue("m3", "marker_music", "start", "b"),
                _cue("m4", "marker_music", "end", "b"),
            ],
            media_declarations={"music": {"a": "a.mp3", "b": "b.mp3"}},
        )
        timeline_path = _write_marker_timeline(
            tmp_path,
            [
                {"id": "m1", "time": 1.0},
                {"id": "m2", "time": 5.0},
                {"id": "m3", "time": 6.0},
                {"id": "m4", "time": 10.0},
            ],
        )
        entries = extract_music_entries(plan, _make_result([]), timeline_path)
        assert len(entries) == 2
        assert entries[0]["name"] == "a"
        assert entries[1]["name"] == "b"

    def test_non_music_segments_ignored(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="标题", segment_type="title_main"),
                SegmentPlan(id="s2", text="内容", segment_type="content"),
            ],
        )
        result = _make_result([
            SegmentResult(id="s1", start=0.0, end=2.0),
            SegmentResult(id="s2", start=2.0, end=4.0),
        ])
        assert extract_music_entries(plan, result) == []

    def test_end_without_start(self, tmp_path):
        plan = _plan_with_cues(
            [_cue("m1", "marker_music", "end", "bgm")],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        entries = extract_music_entries(
            plan,
            _make_result([]),
            _write_marker_timeline(tmp_path, [{"id": "m1", "time": 5.0}]),
        )
        assert entries == []


class TestExtractImageEntries:
    def test_basic_start_end(self, tmp_path):
        plan = _plan_with_cues(
            [
                _cue("i1", "marker_image", "start", "logo"),
                _cue("i2", "marker_image", "end", "logo"),
            ],
            media_declarations={"images": {"logo": "./logo.png"}},
        )
        timeline_path = _write_marker_timeline(
            tmp_path,
            [{"id": "i1", "time": 2.0}, {"id": "i2", "time": 4.0}],
        )
        entries = extract_image_entries(plan, _make_result([]), timeline_path)
        assert len(entries) == 1
        assert entries[0]["name"] == "logo"
        assert entries[0]["src"] == "./logo.png"
        assert entries[0]["start"] == 2.0
        assert entries[0]["end"] == 4.0

    def test_multiple_overlays(self, tmp_path):
        plan = _plan_with_cues(
            [
                _cue("i1", "marker_image", "start", "a"),
                _cue("i2", "marker_image", "end", "a"),
                _cue("i3", "marker_image", "start", "b"),
                _cue("i4", "marker_image", "end", "b"),
            ],
            media_declarations={"images": {"a": "a.png", "b": "b.png"}},
        )
        timeline_path = _write_marker_timeline(
            tmp_path,
            [
                {"id": "i1", "time": 0.0},
                {"id": "i2", "time": 5.0},
                {"id": "i3", "time": 6.0},
                {"id": "i4", "time": 10.0},
            ],
        )
        entries = extract_image_entries(plan, _make_result([]), timeline_path)
        assert len(entries) == 2

    def test_non_image_segments_ignored(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_start bgm]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "bgm"}),
            ],
        )
        result = _make_result([SegmentResult(id="s1", start=0.0, end=0.0)])
        assert extract_image_entries(plan, result) == []


class TestExtractShotVisualEntries:
    def test_no_visuals(self):
        """空 result 返回空列表。"""
        result = ResultManifest()
        assert extract_shot_visual_entries(result) == []

    def test_execution_assets_visual_collected(self):
        plan = PlanManifest(
            segments=[SegmentPlan(id="s1", text="x", segment_type="content", target_duration=2.0)],
            scenes=[
                ScenePlan(
                    id="scene_001",
                    visual_type="stock_image",
                    shots=[ShotPlan(id="shot_001", segment_ids=["s1"])],
                ),
            ],
        )
        assets = ExecutionAssets(
            visual_assets=[
                VisualAsset(
                    shot_id="shot_001",
                    path="/repo/assets/local_image.jpg",
                    width=500,
                    height=631,
                    provider="local",
                ),
            ],
        )

        entries = extract_shot_visual_entries_from_assets(plan, assets)
        assert entries == [{
            "name": "shot_001",
            "src": "/repo/assets/local_image.jpg",
            "start": 0.0,
            "end": 2.0,
            "layout_type": "center_title_body",
            "layout_params": {},
        }]

    def test_execution_assets_visual_uses_timeline_shot_timing(self, tmp_path):
        plan = PlanManifest(
            segments=[SegmentPlan(id="s1", text="x", segment_type="content", target_duration=2.0)],
            scenes=[
                ScenePlan(
                    id="scene_001",
                    visual_type="stock_image",
                    shots=[ShotPlan(id="shot_001", segment_ids=["s1"])],
                ),
            ],
        )
        assets = ExecutionAssets(
            visual_assets=[
                VisualAsset(
                    shot_id="shot_001",
                    path="/repo/assets/local_image.jpg",
                    width=500,
                    height=631,
                    provider="local",
                ),
            ],
        )
        timeline_path = tmp_path / "timeline.json"
        timeline_path.write_text(json.dumps({
            "shots": [{
                "shot_id": "shot_001",
                "scene_id": "scene_001",
                "segment_ids": ["s1"],
                "start": 4.25,
                "end": 8.75,
            }],
        }), encoding="utf-8")

        entries = extract_shot_visual_entries_from_assets(plan, assets, timeline_path=timeline_path)

        assert entries[0]["start"] == 4.25
        assert entries[0]["end"] == 8.75

    def test_text_only_scenes_omitted(self):
        """visual.source == "none" 的 shot 被跳过。"""
        result = ResultManifest(scenes=[
            SceneResult(id="scene_001", shots=[
                ShotResult(id="shot_001", segment_ids=["s1"], start=0.0, end=2.0,
                           visual=VisualResult()),  # 默认空值
            ]),
        ])
        assert extract_shot_visual_entries(result) == []

    def test_stock_image_visual_collected(self):
        """stock_image visual 被正确提取。"""
        result = ResultManifest(scenes=[
            SceneResult(id="scene_001", shots=[
                ShotResult(id="shot_001", segment_ids=["s1"], start=0.0, end=5.0,
                           visual=VisualResult(
                               path="/artifacts/visuals/scene_001/img.jpg",
                               width=1920, height=1080, source="pexels")),
            ]),
        ])
        entries = extract_shot_visual_entries(result)
        assert len(entries) == 1
        assert entries[0]["name"] == "shot_001"
        assert entries[0]["src"] == "/artifacts/visuals/scene_001/img.jpg"
        assert entries[0]["start"] == 0.0
        assert entries[0]["end"] == 5.0

    def test_local_image_visual_collected(self):
        """local provider visual 被作为 per-shot overlay 条目提取。"""
        result = ResultManifest(scenes=[
            SceneResult(id="scene_001", shots=[
                ShotResult(id="shot_001", segment_ids=["s1"], start=1.0, end=3.0,
                           visual=VisualResult(
                               path="/repo/assets/local_image.jpg",
                               width=500, height=631, source="local")),
            ]),
        ])
        entries = extract_shot_visual_entries(result)
        assert len(entries) == 1
        assert entries[0]["name"] == "shot_001"
        assert entries[0]["src"] == "/repo/assets/local_image.jpg"
        assert entries[0]["start"] == 1.0
        assert entries[0]["end"] == 3.0

    def test_multiple_shots_same_scene(self):
        """同一 scene 下的多个 shot 各自产出条目。"""
        result = ResultManifest(scenes=[
            SceneResult(id="scene_001", shots=[
                ShotResult(id="shot_001", segment_ids=["s1"], start=0.0, end=3.0,
                           visual=VisualResult(path="/a.jpg", source="pexels")),
                ShotResult(id="shot_002", segment_ids=["s2"], start=3.0, end=6.0,
                           visual=VisualResult(path="/b.jpg", source="pexels")),
            ]),
        ])
        entries = extract_shot_visual_entries(result)
        assert len(entries) == 2
        assert entries[0]["src"] == "/a.jpg"
        assert entries[1]["src"] == "/b.jpg"

    def test_visual_with_zero_path_omitted(self):
        """visual.path 为空时跳过。"""
        result = ResultManifest(scenes=[
            SceneResult(id="scene_001", shots=[
                ShotResult(id="shot_001", segment_ids=["s1"], start=0.0, end=2.0,
                           visual=VisualResult(path="", source="pexels")),
            ]),
        ])
        assert extract_shot_visual_entries(result) == []


# ========== layout region consumption ==========

def _plan_with_scene_layout(layout_type, layout_params=None):
    return PlanManifest(
        segments=[],
        scenes=[
            ScenePlan(
                id="scene_001",
                visual_type="stock_image",
                layout_type=layout_type,
                layout_params=layout_params or {},
                shots=[ShotPlan(id="shot_001", segment_ids=[])],
            ),
        ],
    )


def test_extract_shot_visual_entries_from_assets_attaches_scene_layout():
    """per-shot visual 条目携带所在 scene 的 layout 契约。"""
    plan = _plan_with_scene_layout(
        "image_top_text_bottom", {"split": "image_focus"},
    )
    assets = ExecutionAssets(visual_assets=[
        VisualAsset(shot_id="shot_001", path="/tmp/img.jpg", provider="local"),
    ])

    entries = extract_shot_visual_entries_from_assets(plan, assets)

    assert len(entries) == 1
    assert entries[0]["layout_type"] == "image_top_text_bottom"
    assert entries[0]["layout_params"] == {"split": "image_focus"}


def test_extract_shot_visual_entries_from_assets_without_layout_fields():
    plan = PlanManifest(segments=[], scenes=[])

    entries = extract_shot_visual_entries_from_assets(plan, ExecutionAssets())

    assert entries == []


def test_attach_image_layout_regions_computes_pixel_rect():
    entries = [{
        "name": "shot_001",
        "src": "/tmp/img.jpg",
        "start": 0.0,
        "end": 1.0,
        "layout_type": "image_top_text_bottom",
        "layout_params": {"split": "balanced", "gap": "normal"},
    }]

    attach_image_layout_regions(entries, 480, 854)

    # image box: x 0.08..0.92, y 0.06..0.50 -> rounded + even dims
    assert entries[0]["region_px"] == {
        "left": 38, "top": 51, "width": 402, "height": 376,
    }


def test_attach_image_layout_regions_skips_without_image_region():
    entries = [{
        "name": "shot_001",
        "src": "/tmp/img.jpg",
        "start": 0.0,
        "end": 1.0,
        "layout_type": "center_title_body",
        "layout_params": {},
    }]

    attach_image_layout_regions(entries, 480, 854)

    assert "region_px" not in entries[0]


def test_attach_image_layout_regions_skips_unknown_layout():
    entries = [{
        "name": "shot_001",
        "src": "/tmp/img.jpg",
        "start": 0.0,
        "end": 1.0,
        "layout_type": "not_a_template",
        "layout_params": {},
    }]

    attach_image_layout_regions(entries, 480, 854)

    assert "region_px" not in entries[0]


def test_attach_image_layout_regions_keeps_plain_entries():
    """marker 图片等无 layout 条目保持原样（legacy 摆放）。"""
    entries = [{"name": "logo", "src": "/tmp/logo.jpg", "start": 0.0, "end": 1.0}]

    attach_image_layout_regions(entries, 480, 854)

    assert entries[0] == {"name": "logo", "src": "/tmp/logo.jpg", "start": 0.0, "end": 1.0}


def _run_build_and_run_ffmpeg(monkeypatch, image_segments, kb_config):
    captured = {}

    def fake_run(cmd, check=True):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ffmpeg_assembler.subprocess, "run", fake_run)
    build_and_run_ffmpeg(
        video_path=Path("base.mp4"),
        music_segments=[],
        image_segments=image_segments,
        base_has_audio=True,
        out_path=Path("out.mp4"),
        video_duration=10.0,
        video_width=480,
        video_height=854,
        ken_burns_config=kb_config,
    )
    cmd = captured["cmd"]
    return cmd[cmd.index("-filter_complex") + 1]


def test_build_and_run_ffmpeg_static_overlay_inside_layout_region(monkeypatch):
    img = {
        "name": "shot_001",
        "src": "/tmp/img.jpg",
        "start": 0.0,
        "end": 1.5,
        "region_px": {"left": 38, "top": 51, "width": 402, "height": 376},
    }

    filter_complex = _run_build_and_run_ffmpeg(monkeypatch, [img], KenBurnsConfig(enabled=False))

    assert "scale=w='if(gt(iw/ih,402/376),402,-2)':h='if(gt(iw/ih,402/376),-2,376)'" in filter_complex
    assert "overlay=x='38+(402-w)/2':y='51+(376-h)/2'" in filter_complex


def test_build_and_run_ffmpeg_ken_burns_inside_layout_region(monkeypatch):
    img = {
        "name": "shot_001",
        "src": "/tmp/img.jpg",
        "start": 0.0,
        "end": 1.5,
        "region_px": {"left": 38, "top": 51, "width": 402, "height": 376},
    }

    filter_complex = _run_build_and_run_ffmpeg(monkeypatch, [img], KenBurnsConfig(enabled=True))

    assert "scale=402:376:force_original_aspect_ratio=increase" in filter_complex
    assert "s=402x376" in filter_complex
    assert "overlay=x='38':y='51'" in filter_complex


def test_build_and_run_ffmpeg_without_region_keeps_legacy_overlay(monkeypatch):
    img = {"name": "logo", "src": "/tmp/img.jpg", "start": 0.0, "end": 1.5}

    filter_complex = _run_build_and_run_ffmpeg(monkeypatch, [img], KenBurnsConfig(enabled=False))

    assert "scale=w='if(gt(iw/ih,288/597),288,-2)':h='if(gt(iw/ih,288/597),-2,597)'" in filter_complex
    assert "overlay=x='288-w/2':y='298-h/2'" in filter_complex
