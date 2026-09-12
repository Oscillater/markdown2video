"""A9 OTIO 导出测试：lowering 结构、确定性、roundtrip、降级与管线登记。"""
from __future__ import annotations

import json
from unittest.mock import patch

import opentimelineio as otio
import pytest

from md2video.timeline.otio_export import (
    DEFAULT_TIMELINE_FPS,
    OTIO_FILENAME,
    export_timeline_otio,
    timeline_to_otio,
    write_otio_artifact,
)
from tests.test_pipeline_artifacts import _make_pipeline, _sole_run_dir


def _sample_timeline() -> dict:
    return {
        "fps": 30,
        "shots": [
            {
                "shot_id": "shot_001",
                "scene_id": "scene_001",
                "segment_ids": ["seg_001"],
                "start": 0.0,
                "end": 2.5,
                "layout_type": "center_title_body",
            },
            {
                "shot_id": "shot_002",
                "scene_id": "scene_001",
                "segment_ids": ["seg_002"],
                "start": 2.5,
                "end": 4.0,
            },
        ],
        "text": [
            {
                "segment_id": "seg_001",
                "segment_type": "section_header",
                "text": "标题",
                "start": 0.0,
                "end": 2.0,
                "shot_id": "shot_001",
                "scene_id": "scene_001",
            },
            {
                "segment_id": "seg_002",
                "segment_type": "content",
                "text": "正文",
                "start": 2.6,
                "end": 3.9,
                "shot_id": "shot_002",
                "scene_id": "scene_001",
            },
            {"segment_id": "seg_timed", "text": "按时间归属", "start": 0.5, "end": 1.0},
        ],
        "markers": [
            {
                "id": "mk_logo",
                "cue_type": "marker_image",
                "kind": "logo",
                "name": "logo",
                "time": 1.0,
                "shot_id": "shot_001",
                "scene_id": "scene_001",
            },
            {"id": "mk_bgm", "cue_type": "marker_music", "name": "bgm", "time": 9.9},
        ],
    }


def _clip_by_name(otio_timeline, shot_id: str):
    matches = [c for c in otio_timeline.tracks[0] if c.name == shot_id]
    assert len(matches) == 1, f"expected one clip {shot_id}, got {matches}"
    return matches[0]


def test_lowering_structure_shots_clips_and_metadata():
    timeline = timeline_to_otio(_sample_timeline(), name="run-1")

    assert timeline.name == "run-1"
    track = timeline.tracks[0]
    assert track.kind == otio.schema.TrackKind.Video
    assert [c.name for c in track] == ["shot_001", "shot_002"]

    first, second = track
    assert first.source_range.start_time.to_seconds() == 0.0
    assert first.source_range.duration.to_seconds() == 2.5
    assert second.source_range.start_time.to_seconds() == 2.5
    assert second.source_range.duration.to_seconds() == 1.5
    # OTIO metadata 的 list 是自有容器类型，比较前转 list
    assert first.metadata["md2video"]["scene_id"] == "scene_001"
    assert list(first.metadata["md2video"]["segment_ids"]) == ["seg_001"]
    assert first.metadata["md2video"]["layout_type"] == "center_title_body"


def test_text_facts_attach_by_shot_id_then_time():
    """归属语义：显式 shot_id > 时间落入的 shot；落在任何 shot 之外的才进 orphan。"""
    timeline = timeline_to_otio(_sample_timeline())
    first = _clip_by_name(timeline, "shot_001")
    second = _clip_by_name(timeline, "shot_002")

    first_texts = first.metadata["md2video"]["text"]
    assert [t["segment_id"] for t in first_texts] == ["seg_001", "seg_timed"]
    assert first_texts[0]["text"] == "标题"

    second_texts = second.metadata["md2video"]["text"]
    assert [t["segment_id"] for t in second_texts] == ["seg_002"]


def test_text_outside_all_shots_goes_to_timeline_orphans():
    timeline_data = _sample_timeline()
    timeline_data["shots"] = []
    timeline_data["text"] = [
        {"segment_id": "seg_orphan", "text": "无归属", "start": 0.5, "end": 1.0},
    ]
    timeline = timeline_to_otio(timeline_data)
    assert [c.name for c in timeline.tracks[0]] == []
    orphans = timeline.metadata["md2video"]["orphan_text"]
    assert [t["segment_id"] for t in orphans] == ["seg_orphan"]


def test_marker_cues_attach_to_owning_shot_clip():
    timeline = timeline_to_otio(_sample_timeline())
    first = _clip_by_name(timeline, "shot_001")
    second = _clip_by_name(timeline, "shot_002")

    assert [m.name for m in first.markers] == ["mk_logo"]
    logo = first.markers[0]
    assert logo.metadata["md2video"]["cue_type"] == "marker_image"
    # marker 绝对时间 1.0 相对 shot_001 起点 0.0 的偏移
    assert logo.marked_range.start_time.to_seconds() == pytest.approx(1.0)
    assert logo.marked_range.duration.to_seconds() == 0.0

    # 无 shot_id 的 marker 按时间归入落入的 shot（9.9 >= 末尾 → 末 shot）
    assert [m.name for m in second.markers] == ["mk_bgm"]


def test_missing_fps_falls_back_to_contract_default():
    timeline_data = _sample_timeline()
    timeline_data.pop("fps")
    timeline = timeline_to_otio(timeline_data)
    assert timeline.metadata["md2video"]["fps"] == DEFAULT_TIMELINE_FPS


def test_bad_entries_skipped_not_raised():
    timeline_data = {
        "shots": [None, "junk", {"shot_id": "", "start": 0.0, "end": 1.0}, {"shot_id": "ok", "start": 0.0, "end": 1.0}],
        "text": [None, {"segment_id": "ok", "start": 0.0, "end": 0.5, "shot_id": "ok"}, "junk"],
        "markers": [None, {"id": "ok", "time": 0.2, "shot_id": "ok"}, {"id": "bad_time", "time": "NaN"}],
    }
    timeline = timeline_to_otio(timeline_data)
    # 无 shot_id 的条目被宽容地给合成名，不抛错；非 dict / 坏时间被跳过
    assert [c.name for c in timeline.tracks[0]] == ["shot@0.000", "ok"]
    ok_clip = _clip_by_name(timeline, "ok")
    assert [m.name for m in ok_clip.markers] == ["ok"]


def test_serialization_is_deterministic(tmp_path):
    first = tmp_path / "a.otio"
    second = tmp_path / "b.otio"
    export_timeline_otio(_sample_timeline(), first)
    export_timeline_otio(_sample_timeline(), second)
    assert first.read_bytes() == second.read_bytes()


def test_roundtrip_preserves_clips_and_metadata(tmp_path):
    path = tmp_path / OTIO_FILENAME
    export_timeline_otio(_sample_timeline(), path)

    restored = otio.adapters.read_from_file(str(path))
    track = restored.tracks[0]
    assert [c.name for c in track] == ["shot_001", "shot_002"]
    assert list(track[0].metadata["md2video"]["segment_ids"]) == ["seg_001"]
    assert track[0].metadata["md2video"]["text"][0]["segment_id"] == "seg_001"
    assert track[0].markers[0].name == "mk_logo"


def test_write_otio_artifact_degrades_with_warning_on_failure(tmp_path):
    with patch(
        "md2video.timeline.otio_export.timeline_to_otio",
        side_effect=RuntimeError("boom"),
    ):
        path, warning = write_otio_artifact(_sample_timeline(), tmp_path / "x.otio")
    assert path is None
    assert "boom" in warning
    assert not (tmp_path / "x.otio").exists()


def test_write_otio_artifact_skipped_without_opentimelineio(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _hide_otio(name, *args, **kwargs):
        if name.startswith("opentimelineio"):
            raise ImportError(f"hidden for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _hide_otio)
    path, warning = write_otio_artifact(_sample_timeline(), tmp_path / "x.otio")
    assert path is None
    assert "opentimelineio not installed" in warning


def test_pipeline_registers_otio_in_artifact_index(tmp_path):
    plan_path, _ = _write_minimal_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    pipeline = _make_pipeline(tmp_path)

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        pipeline.run_plan(str(plan_path), str(output_path))

    run_dir = _sole_run_dir(tmp_path)
    otio_path = run_dir / OTIO_FILENAME
    assert otio_path.exists()

    restored = otio.adapters.read_from_file(str(otio_path))
    assert restored.metadata["md2video"]["generator"] == "markdown2video"

    raw_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert raw_result["artifact_index"]["otio_timeline"] == str(otio_path)


def _write_minimal_plan(tmp_path):
    from md2video.manifest.schema import PlanManifest, SegmentPlan

    plan_path = tmp_path / "minimal_plan.json"
    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="seg_001",
                text="Minimal silent segment.",
                segment_type="content",
                audio_request=None,
            ),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "shots": [{
                "id": "shot_001",
                "segment_ids": ["seg_001"],
            }],
            "section_context": "minimal",
        }],
        media_declarations={},
    )
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return plan_path, None
