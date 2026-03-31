"""Shared fixtures for md2video tests."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from md2video.manifest.schema import (
    AudioRequest,
    AudioResult,
    PlanManifest,
    ResultManifest,
    SegmentPlan,
    SegmentResult,
    VisualResult,
)


# ========== Pydantic Model Fixtures ==========


@pytest.fixture
def sample_audio_request():
    return AudioRequest()


@pytest.fixture
def sample_segment_plan():
    return SegmentPlan(
        id="seg_001",
        text="测试文本",
        segment_type="content",
        audio_request=AudioRequest(),
    )


@pytest.fixture
def sample_plan_manifest():
    return PlanManifest(
        version="1",
        segments=[
            SegmentPlan(
                id="seg_001", text="大标题", segment_type="title_main",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="seg_002", text="二级标题", segment_type="title_sub",
                audio_request=AudioRequest(),
            ),
            SegmentPlan(
                id="seg_003", text="小重山", segment_type="section_header",
                audio_request=AudioRequest(), section_context="小重山",
            ),
            SegmentPlan(
                id="seg_004", text="测试内容。", segment_type="content",
                audio_request=AudioRequest(), section_context="小重山",
            ),
        ],
        media_declarations={"music": {"bgm": "./music.mp3"}},
    )


@pytest.fixture
def sample_result_manifest():
    return ResultManifest(
        segments=[
            SegmentResult(id="seg_001", start=0.0, end=2.0,
                          audio=AudioResult(path="seg_001.wav", duration=2.0)),
            SegmentResult(id="seg_002", start=2.0, end=4.0,
                          audio=AudioResult(path="seg_002.wav", duration=2.0)),
            SegmentResult(id="seg_003", start=4.0, end=6.0,
                          audio=AudioResult(path="seg_003.wav", duration=2.0)),
            SegmentResult(id="seg_004", start=6.0, end=8.0,
                          audio=AudioResult(path="seg_004.wav", duration=2.0)),
        ],
    )


@pytest.fixture
def plan_with_music_markers():
    """Plan with music start/end markers and a music declaration."""
    return PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="大标题", segment_type="title_main",
                        audio_request=AudioRequest()),
            SegmentPlan(id="seg_002", text="内容段落。", segment_type="content",
                        audio_request=AudioRequest(), section_context="S1"),
            SegmentPlan(id="seg_003", text="[music_start bgm]", segment_type="marker_music",
                        marker_data={"kind": "start", "name": "bgm"}),
            SegmentPlan(id="seg_004", text="更多内容。", segment_type="content",
                        audio_request=AudioRequest(), section_context="S1"),
            SegmentPlan(id="seg_005", text="[music_end bgm]", segment_type="marker_music",
                        marker_data={"kind": "end", "name": "bgm"}),
        ],
        media_declarations={"music": {"bgm": "./music.mp3"}},
    )


@pytest.fixture
def plan_with_image_markers():
    """Plan with image start/end markers and an image declaration."""
    return PlanManifest(
        segments=[
            SegmentPlan(id="seg_001", text="大标题", segment_type="title_main",
                        audio_request=AudioRequest()),
            SegmentPlan(id="seg_002", text="[image_start logo]", segment_type="marker_image",
                        marker_data={"kind": "start", "name": "logo"}),
            SegmentPlan(id="seg_003", text="内容。", segment_type="content",
                        audio_request=AudioRequest(), section_context="S1"),
            SegmentPlan(id="seg_004", text="[image_end logo]", segment_type="marker_image",
                        marker_data={"kind": "end", "name": "logo"}),
        ],
        media_declarations={"images": {"logo": "./logo.png"}},
    )


@pytest.fixture
def result_with_timings():
    """Result manifest matching plan_with_music_markers and plan_with_image_markers."""
    return ResultManifest(
        segments=[
            SegmentResult(id="seg_001", start=0.0, end=2.0,
                          audio=AudioResult(path="seg_001.wav", duration=2.0)),
            SegmentResult(id="seg_002", start=2.0, end=4.0,
                          audio=AudioResult(path="seg_002.wav", duration=2.0)),
            SegmentResult(id="seg_003", start=4.0, end=4.0,
                          audio=None),
            SegmentResult(id="seg_004", start=4.0, end=6.0,
                          audio=AudioResult(path="seg_004.wav", duration=2.0)),
            SegmentResult(id="seg_005", start=6.0, end=6.0,
                          audio=None),
        ],
    )


# ========== Filesystem Fixtures ==========


@pytest.fixture
def minimal_md(tmp_path):
    """写入最简 Markdown 文件并返回路径。"""
    p = tmp_path / "minimal.md"
    p.write_text(
        "# 大标题\n"
        "## 二级标题\n"
        "### 小重山\n"
        "测试文本\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def full_md(tmp_path):
    """写入完整示例 Markdown 文件并返回路径。"""
    p = tmp_path / "full.md"
    p.write_text(
        '[music:name="222",src="./music.mp3"]\n'
        "# 大标题\n"
        "## 二级标题\n"
        "### 小重山\n"
        "12345\n"
        "### 长长长标题测试测试测试\n"
        "段落第一句，这是这个段落段落的第二句\n"
        "另一个段落\n"
        "### 这里也是标题\n"
        "嗨嗨嗨\n"
        "### 多个段落测试\n"
        "1\n"
        "### 多个段落测试2\n"
        "2\n"
        "### 多个段落测试3\n"
        "3\n"
        "### 多个段落测试4\n"
        "4\n"
        "### 看看是否正常删除\n"
        "结束了\n"
        "---\n"
        "下面是附录\n"
        "[music_start 222]\n"
        "你问我要去向何方\n"
        "我指着大海的方向\n"
        "[music_end 222]\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def audio_file(tmp_path):
    """创建一个最小的有效 WAV 文件并返回路径。"""
    p = tmp_path / "test_audio.wav"
    # 写入最小 WAV: 44-byte header + silence
    data = bytearray()
    # RIFF header
    data.extend(b"RIFF")
    data.extend(struct.pack("<I", 36))  # file size - 8
    data.extend(b"WAVE")
    # fmt chunk
    data.extend(b"fmt ")
    data.extend(struct.pack("<I", 16))  # chunk size
    data.extend(struct.pack("<H", 1))   # PCM format
    data.extend(struct.pack("<H", 1))   # mono
    data.extend(struct.pack("<I", 44100))  # sample rate
    data.extend(struct.pack("<I", 88200))  # byte rate
    data.extend(struct.pack("<H", 2))   # block align
    data.extend(struct.pack("<H", 16))  # bits per sample
    # data chunk
    data.extend(b"data")
    data.extend(struct.pack("<I", 0))   # data size (0 = no audio data)
    p.write_bytes(data)
    return p
