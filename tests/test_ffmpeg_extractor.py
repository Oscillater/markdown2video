"""Tests for extract_music_entries, extract_image_entries and extract_shot_visual_entries in ffmpeg_assembler."""
from __future__ import annotations

from md2video.assembler.ffmpeg_assembler import (
    extract_image_entries, extract_music_entries, extract_shot_visual_entries,
)
from md2video.manifest.schema import (
    AudioResult,
    PlanManifest,
    ResultManifest,
    SceneResult,
    SegmentPlan,
    SegmentResult,
    ShotResult,
    VisualResult,
)


def _make_plan(segments, media_declarations=None):
    return PlanManifest(segments=segments, media_declarations=media_declarations or {})


def _make_result(segment_results):
    return ResultManifest(segments=segment_results)


class TestExtractMusicEntries:
    def test_basic_start_end(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_start bgm]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "bgm"}),
                SegmentPlan(id="s2", text="内容。", segment_type="content"),
                SegmentPlan(id="s3", text="[music_end bgm]", segment_type="marker_music",
                            marker_data={"kind": "end", "name": "bgm"}),
            ],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        result = _make_result([
            SegmentResult(id="s1", start=4.0, end=4.0),
            SegmentResult(id="s2", start=4.0, end=6.0),
            SegmentResult(id="s3", start=6.0, end=6.0),
        ])
        entries = extract_music_entries(plan, result)
        assert len(entries) == 1
        assert entries[0]["name"] == "bgm"
        assert entries[0]["src"] == "./music.mp3"
        assert entries[0]["start"] == 4.0
        assert entries[0]["end"] == 6.0

    def test_missing_src(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_start unknown]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "unknown"}),
            ],
        )
        result = _make_result([SegmentResult(id="s1", start=0.0, end=0.0)])
        entries = extract_music_entries(plan, result)
        assert len(entries) == 1
        assert entries[0]["src"] is None

    def test_no_result_timing(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_start bgm]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "bgm"}),
            ],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        result = _make_result([])
        entries = extract_music_entries(plan, result)
        assert len(entries) == 1
        assert entries[0]["start"] == 0.0

    def test_multiple_pairs(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_start a]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "a"}),
                SegmentPlan(id="s2", text="[music_end a]", segment_type="marker_music",
                            marker_data={"kind": "end", "name": "a"}),
                SegmentPlan(id="s3", text="[music_start b]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "b"}),
                SegmentPlan(id="s4", text="[music_end b]", segment_type="marker_music",
                            marker_data={"kind": "end", "name": "b"}),
            ],
            media_declarations={"music": {"a": "a.mp3", "b": "b.mp3"}},
        )
        result = _make_result([
            SegmentResult(id="s1", start=1.0, end=1.0),
            SegmentResult(id="s2", start=5.0, end=5.0),
            SegmentResult(id="s3", start=6.0, end=6.0),
            SegmentResult(id="s4", start=10.0, end=10.0),
        ])
        entries = extract_music_entries(plan, result)
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

    def test_end_without_start(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[music_end bgm]", segment_type="marker_music",
                            marker_data={"kind": "end", "name": "bgm"}),
            ],
            media_declarations={"music": {"bgm": "./music.mp3"}},
        )
        result = _make_result([SegmentResult(id="s1", start=5.0, end=5.0)])
        entries = extract_music_entries(plan, result)
        assert entries == []


class TestExtractImageEntries:
    def test_basic_start_end(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[image_start logo]", segment_type="marker_image",
                            marker_data={"kind": "start", "name": "logo"}),
                SegmentPlan(id="s2", text="内容", segment_type="content"),
                SegmentPlan(id="s3", text="[image_end logo]", segment_type="marker_image",
                            marker_data={"kind": "end", "name": "logo"}),
            ],
            media_declarations={"images": {"logo": "./logo.png"}},
        )
        result = _make_result([
            SegmentResult(id="s1", start=2.0, end=2.0),
            SegmentResult(id="s2", start=2.0, end=4.0),
            SegmentResult(id="s3", start=4.0, end=4.0),
        ])
        entries = extract_image_entries(plan, result)
        assert len(entries) == 1
        assert entries[0]["name"] == "logo"
        assert entries[0]["src"] == "./logo.png"
        assert entries[0]["start"] == 2.0
        assert entries[0]["end"] == 4.0

    def test_multiple_overlays(self):
        plan = _make_plan(
            segments=[
                SegmentPlan(id="s1", text="[image_start a]", segment_type="marker_image",
                            marker_data={"kind": "start", "name": "a"}),
                SegmentPlan(id="s2", text="[image_end a]", segment_type="marker_image",
                            marker_data={"kind": "end", "name": "a"}),
                SegmentPlan(id="s3", text="[image_start b]", segment_type="marker_image",
                            marker_data={"kind": "start", "name": "b"}),
                SegmentPlan(id="s4", text="[image_end b]", segment_type="marker_image",
                            marker_data={"kind": "end", "name": "b"}),
            ],
            media_declarations={"images": {"a": "a.png", "b": "b.png"}},
        )
        result = _make_result([
            SegmentResult(id="s1", start=0.0, end=0.0),
            SegmentResult(id="s2", start=5.0, end=5.0),
            SegmentResult(id="s3", start=6.0, end=6.0),
            SegmentResult(id="s4", start=10.0, end=10.0),
        ])
        entries = extract_image_entries(plan, result)
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
