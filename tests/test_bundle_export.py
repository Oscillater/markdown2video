"""解法 4 混剪素材包测试：SRT lowering、EDL 独立读回、切片、素材拷贝、管线登记。

层次对应：①语法（ffmpeg/otio 独立实现能解析）②语义（内容与 timeline 事实
一致、确定性）。④实机验收（消费级软件真导入）是人工一次性检查，不进 CI。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import opentimelineio as otio
import pytest

from md2video.manifest.schema import (
    AudioAsset,
    ExecutionAssets,
    PlanManifest,
    SegmentPlan,
)
from md2video.timeline.bundle_export import (
    EDL_FILENAME,
    README_FILENAME,
    SRT_FILENAME,
    _seconds_to_srt_time,
    build_srt,
    export_bundle,
)
from tests.test_pipeline_artifacts import (
    FakeRenderTool,
    _make_pipeline,
    _sole_run_dir,
)


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
                "segment_type": "title_main",
                "text": "全片标题",
                "start": 0.0,
                "end": 4.0,
                "shot_id": "shot_001",
            },
            {
                "segment_id": "seg_002",
                "segment_type": "section_header",
                "text": "节标题",
                "start": 0.5,
                "end": 2.0,
                "shot_id": "shot_001",
            },
            {
                "segment_id": "seg_003",
                "segment_type": "content",
                "text": "第一句口播",
                "start": 2.92,
                "end": 7.048,
                "shot_id": "shot_002",
            },
            {
                "segment_id": "seg_004",
                "segment_type": "appendix",
                "text": "第二句口播",
                "start": 7.048,
                "end": 11.128,
                "shot_id": "shot_002",
            },
        ],
        "markers": [],
    }


def test_srt_time_formatting_boundaries():
    assert _seconds_to_srt_time(0.0) == "00:00:00,000"
    assert _seconds_to_srt_time(7.048) == "00:00:07,048"
    assert _seconds_to_srt_time(3661.5) == "01:01:01,500"
    assert _seconds_to_srt_time(-1.0) == "00:00:00,000"


def test_build_srt_golden_content_and_filters_screen_text():
    # 只剩 content/appendix 两条；title_main 与 section_header 是挂屏文字
    assert build_srt(_sample_timeline()) == (
        "1\n00:00:02,920 --> 00:00:07,048\n第一句口播\n"
        "\n"
        "2\n00:00:07,048 --> 00:00:11,128\n第二句口播\n"
    )


def test_build_srt_skips_bad_entries_and_sorts_by_start():
    timeline = {
        "text": [
            {"segment_id": "bad_range", "segment_type": "content", "text": "倒置", "start": 2.0, "end": 1.0},
            {"segment_id": "empty_text", "segment_type": "content", "text": "   ", "start": 0.0, "end": 1.0},
            {"segment_id": "no_time", "segment_type": "content", "text": "无时间"},
            None,
            "junk",
            {"segment_id": "b", "segment_type": "content", "text": "后", "start": 3.0, "end": 4.0},
            {"segment_id": "a", "segment_type": "content", "text": "先", "start": 1.0, "end": 2.0},
        ],
    }
    assert build_srt(timeline) == (
        "1\n00:00:01,000 --> 00:00:02,000\n先\n"
        "\n"
        "2\n00:00:03,000 --> 00:00:04,000\n后\n"
    )


def test_export_bundle_writes_text_artifacts_and_degrades_clips(tmp_path):
    base_dir = tmp_path / "md"
    base_dir.mkdir()
    (base_dir / "cover.jpg").write_bytes(b"fake jpg")
    (base_dir / "music.mp3").write_bytes(b"fake mp3")
    # edge-tts 实况：请求 .wav 但字节是 mp3
    fake_mp3_named_wav = tmp_path / "seg_voice.wav"
    fake_mp3_named_wav.write_bytes(b"ID3\x04fake mp3 data")
    fake_real_wav = tmp_path / "seg_real.wav"
    fake_real_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt fake")

    plan = PlanManifest(
        segments=[
            SegmentPlan(
                id="seg_003",
                text="第一句口播",
                segment_type="content",
                audio_request=None,
            ),
        ],
        scenes=[],
        media_declarations={
            "images": {"cover": "cover.jpg"},
            "music": {"bgm": "music.mp3"},
        },
    )
    assets = ExecutionAssets(
        audio_assets=[
            AudioAsset(
                segment_id="seg_003",
                path=str(fake_mp3_named_wav),
                duration=4.1,
                provider="edge-tts",
                cache_key="k",
            ),
            AudioAsset(
                segment_id="seg_004",
                path=str(fake_real_wav),
                duration=1.9,
                provider="edge-tts",
                cache_key="k",
            ),
        ],
    )

    missing_video = tmp_path / "not_rendered.mp4"
    bundle_dir, warnings = export_bundle(
        _sample_timeline(),
        missing_video,
        tmp_path / "bundle",
        plan=plan,
        execution_assets=assets,
        base_dir=base_dir,
        run_name="run-1",
    )

    assert bundle_dir == tmp_path / "bundle"
    assert (bundle_dir / SRT_FILENAME).read_text(encoding="utf-8").startswith(
        "1\n00:00:02,920 --> 00:00:07,048\n第一句口播\n"
    )
    assert (bundle_dir / README_FILENAME).read_text(encoding="utf-8").startswith(
        "markdown2video 混剪素材包"
    )
    # 成片缺失：clips 降级为 warning，其余产物照常
    assert any("bundle clips failed" in w or "clips skipped" in w for w in warnings)
    assert not any((bundle_dir / "clips").iterdir())
    # EDL 存在且可被独立实现读回（cmx3600 适配器）
    edl_text = (bundle_dir / EDL_FILENAME).read_text(encoding="utf-8")
    assert "shot_001" in edl_text and "shot_002" in edl_text
    # 素材按声明拷贝
    assert (bundle_dir / "assets" / "images" / "cover.jpg").read_bytes() == b"fake jpg"
    assert (bundle_dir / "assets" / "music" / "bgm.mp3").read_bytes() == b"fake mp3"
    # 名不副实的音频按内容纠正扩展名（消费级软件按扩展名验格式）
    assert (bundle_dir / "assets" / "audio" / "seg_003.mp3").read_bytes() == b"ID3\x04fake mp3 data"
    assert (bundle_dir / "assets" / "audio" / "seg_004.wav").read_bytes() == b"RIFF\x24\x00\x00\x00WAVEfmt fake"
    assert not (bundle_dir / "assets" / "audio" / "seg_003.wav").exists()


def test_export_bundle_text_artifacts_are_deterministic(tmp_path):
    outputs = []
    for index in ("a", "b"):
        bundle_dir, warnings = export_bundle(
            _sample_timeline(),
            tmp_path / "missing.mp4",
            tmp_path / f"bundle_{index}",
            run_name="run-1",
        )
        assert warnings == [
            f"final video missing ({tmp_path / 'missing.mp4'}); bundle clips skipped"
        ]
        outputs.append(bundle_dir)
    for filename in (SRT_FILENAME, EDL_FILENAME, README_FILENAME):
        assert (outputs[0] / filename).read_bytes() == (outputs[1] / filename).read_bytes()


def test_bundle_edl_independent_readback_matches_shot_order_and_ratios(tmp_path):
    bundle_dir, warnings = export_bundle(
        _sample_timeline(),
        tmp_path / "missing.mp4",
        tmp_path / "bundle",
        run_name="run-1",
    )
    assert warnings  # 成片缺失的降级说明，不影响 EDL
    edl_text = (bundle_dir / EDL_FILENAME).read_text(encoding="utf-8")
    # 30fps 帧量化时码直接落在文本里：0s / 2.5s(75f) / 4.0s(120f)，
    # 且事件边界共用同一时码
    assert "00:00:00:00" in edl_text
    assert "00:00:02:15" in edl_text
    assert "00:00:04:00" in edl_text

    restored = otio.adapters.read_from_file(str(bundle_dir / EDL_FILENAME))
    events = list(restored.tracks[0])
    assert [event.name for event in events] == ["shot_001", "shot_002"]

    # CMX3600 不携带可靠帧率，读回秒数因实现假设而异——只断言结构：
    # 顺序、首事件从 0 开始、事件首尾相接
    first_range = events[0].trimmed_range_in_parent()
    second_range = events[1].trimmed_range_in_parent()
    assert first_range.start_time.value == 0
    assert second_range.start_time.value == pytest.approx(
        first_range.start_time.value + first_range.duration.value,
    )


def _ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def _ffprobe_resolution(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    width, height = (int(v) for v in proc.stdout.strip().split("x")[:2])
    return width, height


def _make_real_video(path: Path, duration: float = 3.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True,
    )


def test_clip_cutting_frame_accurate_and_clamped_to_duration(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not available")
    final_video = tmp_path / "final.mp4"
    _make_real_video(final_video, duration=3.0)

    timeline = {
        "fps": 30,
        "shots": [
            {"shot_id": "shot_001", "start": 0.0, "end": 1.0},
            # end 超出成片时长 → 截到 3.0
            {"shot_id": "shot_002", "start": 1.0, "end": 5.0},
        ],
        "text": [],
        "markers": [],
    }
    bundle_dir, warnings = export_bundle(
        timeline, final_video, tmp_path / "bundle",
    )
    assert warnings == []

    clips = sorted((bundle_dir / "clips").glob("*.mp4"))
    assert [clip.name for clip in clips] == ["shot_001.mp4", "shot_002.mp4"]
    assert _ffprobe_duration(clips[0]) == pytest.approx(1.0, abs=0.1)
    assert _ffprobe_duration(clips[1]) == pytest.approx(2.0, abs=0.1)
    assert _ffprobe_resolution(clips[0]) == (320, 240)


class _TimelineRenderTool(FakeRenderTool):
    """在 FakeRenderTool 基础上写一份带 shot 与口播 text 的 timeline。"""

    def execute(self, input_data):
        receipt = super().execute(input_data)
        Path(receipt["timeline_path"]).write_text(
            json.dumps({
                "fps": 30,
                "shots": [{
                    "shot_id": "shot_001",
                    "scene_id": "scene_001",
                    "segment_ids": ["seg_001"],
                    "start": 0.0,
                    "end": 2.0,
                    "layout_type": "center_title_body",
                }],
                "text": [{
                    "segment_id": "seg_001",
                    "segment_type": "content",
                    "text": "你好世界",
                    "start": 0.2,
                    "end": 1.8,
                    "shot_id": "shot_001",
                    "scene_id": "scene_001",
                }],
                "markers": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        return receipt


def _write_minimal_plan(tmp_path: Path) -> Path:
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
    return plan_path


def test_pipeline_registers_bundle_in_artifact_index(tmp_path):
    plan_path = _write_minimal_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    pipeline = _make_pipeline(tmp_path, render_tool=_TimelineRenderTool(tmp_path))
    pipeline.export_bundle = True

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        pipeline.run_plan(str(plan_path), str(output_path))

    run_dir = _sole_run_dir(tmp_path)
    bundle_dir = run_dir / "bundle"
    assert (bundle_dir / SRT_FILENAME).read_text(encoding="utf-8") == (
        "1\n00:00:00,200 --> 00:00:01,800\n你好世界\n"
    )
    assert (bundle_dir / EDL_FILENAME).is_file()

    raw_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert raw_result["artifact_index"]["bundle"] == str(bundle_dir)
    # 装配器被 mock、成片不存在：clips 降级为 warning，不阻断交付
    assert any("bundle clips" in w for w in raw_result["warnings"])


def test_bundle_disabled_by_default(tmp_path):
    plan_path = _write_minimal_plan(tmp_path)
    output_path = tmp_path / "output.mp4"
    pipeline = _make_pipeline(tmp_path, render_tool=_TimelineRenderTool(tmp_path))

    with patch("md2video.assembler.ffmpeg_assembler.FFmpegAssembler") as assembler_cls:
        assembler_cls.return_value.assemble.return_value = output_path
        pipeline.run_plan(str(plan_path), str(output_path))

    run_dir = _sole_run_dir(tmp_path)
    assert not (run_dir / "bundle").exists()
    raw_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert "bundle" not in raw_result["artifact_index"]
