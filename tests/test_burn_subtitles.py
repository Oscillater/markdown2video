"""烧录字幕测试：提取白名单/朗读过滤、ASS 构建、滤镜路径转义、真 ffmpeg 烧录。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from md2video.assembler.ffmpeg_assembler import build_and_run_ffmpeg
from md2video.assembler.subtitles import (
    _ass_time,
    build_ass_file,
    escape_filter_path,
    extract_subtitle_entries,
)
from md2video.manifest.schema import (
    AudioAsset,
    AudioRequest,
    ExecutionAssets,
    PlanManifest,
    SegmentPlan,
)


def _plan() -> PlanManifest:
    return PlanManifest(
        segments=[
            SegmentPlan(id="t1", text="标题", segment_type="title_main"),
            SegmentPlan(id="hdr1", text="小节", segment_type="section_header",
                        audio_request=AudioRequest()),
            SegmentPlan(id="s1", text="第一句解说。", segment_type="content",
                        audio_request=AudioRequest()),
            SegmentPlan(id="s2", text="静默正文，没有配音。", segment_type="content",
                        audio_request=None),
            SegmentPlan(id="s3", text="结尾一句。", segment_type="appendix",
                        audio_request=AudioRequest()),
        ],
        scenes=[],
    )


def _timeline(tmp_path: Path) -> Path:
    data = {
        "text": [
            {"segment_id": "t1", "segment_type": "title_main", "text": "标题",
             "start": 0.0, "end": 1.0},
            {"segment_id": "hdr1", "segment_type": "section_header", "text": "小节",
             "start": 1.0, "end": 2.0},
            {"segment_id": "s1", "segment_type": "content", "text": "第一句解说。",
             "start": 2.0, "end": 5.0},
            {"segment_id": "s2", "segment_type": "content", "text": "静默正文，没有配音。",
             "start": 5.0, "end": 7.0},
            {"segment_id": "s3", "segment_type": "appendix", "text": "结尾一句。",
             "start": 7.0, "end": 9.0},
        ],
    }
    path = tmp_path / "timeline.json"
    path.write_text(__import__("json").dumps(data), encoding="utf-8")
    return path


def _assets(*segment_ids: str) -> ExecutionAssets:
    return ExecutionAssets(
        audio_assets=[
            AudioAsset(
                segment_id=segment_id,
                path=f"audio/{segment_id}.mp3",
                duration=2.0,
                provider="edge-tts",
                cache_key=f"key-{segment_id}",
            )
            for segment_id in segment_ids
        ],
    )


def test_extract_keeps_only_narrated_content_and_appendix(tmp_path):
    entries = extract_subtitle_entries(
        _plan(), _timeline(tmp_path), _assets("s1", "s3", "hdr1"),
    )

    # 白名单 content/appendix + 朗读事实；标题与 header 永不进字幕，
    # s2 是静默段（无音频资产）不上字幕
    assert [e["segment_id"] for e in entries] == ["s1", "s3"]
    assert entries[0]["text"] == "第一句解说。"


def test_extract_falls_back_to_plan_audio_request(tmp_path):
    """无 execution-assets（旧路径）→ 按 plan 的 audio_request 判定朗读。"""
    entries = extract_subtitle_entries(_plan(), _timeline(tmp_path), None)

    assert [e["segment_id"] for e in entries] == ["s1", "s3"]


def test_extract_missing_timeline_returns_empty(tmp_path):
    assert extract_subtitle_entries(_plan(), tmp_path / "missing.json", None) == []


def test_ass_time_format():
    assert _ass_time(0.0) == "0:00:00.00"
    assert _ass_time(65.66) == "0:01:05.66"
    assert _ass_time(7299.99) == "2:01:39.99"


def test_ass_file_is_deterministic_with_dialogues(tmp_path):
    entries = [
        {"segment_id": "s1", "text": "第一句，带逗号。", "start": 2.0, "end": 5.0},
        {"segment_id": "s3", "text": "结尾一句。", "start": 7.0, "end": 9.0},
    ]
    first = build_ass_file(entries, 480, 854, tmp_path / "a.ass")
    second = build_ass_file(entries, 480, 854, tmp_path / "b.ass")

    assert first.read_bytes() == second.read_bytes()
    content = first.read_text(encoding="utf-8")
    assert "PlayResX: 480" in content
    assert "PlayResY: 854" in content
    assert content.count("Dialogue: 0,") == 2
    assert "Dialogue: 0,0:00:02.00,0:00:05.00,Sub,,0,0,0,,第一句，带逗号。" in content


def test_ass_text_sanitizes_override_braces(tmp_path):
    build_ass_file(
        [{"segment_id": "s1", "text": "危险{\\b1}", "start": 0.0, "end": 1.0}],
        480, 854, tmp_path / "s.ass",
    )
    content = (tmp_path / "s.ass").read_text(encoding="utf-8")
    assert "危险(\\b1)" in content  # 花括号换成括号，override 标签失效
    assert "Dialogue: 0,0:00:00.00,0:00:01.00" in content


def test_long_cjk_line_is_pre_wrapped(tmp_path):
    """实测 libass 对无空格中文长句不断行（水平裁边）→ 构建期手动折行。

    480 宽、38px 字号、40 边距 → 每行 10 字；22 字长句折成 3 行。"""
    long_text = "想象圆上有一个点，从最右边出发，逆时针转圈。"
    build_ass_file(
        [{"segment_id": "s1", "text": long_text, "start": 0.0, "end": 1.0}],
        480, 854, tmp_path / "w.ass",
    )
    content = (tmp_path / "w.ass").read_text(encoding="utf-8")
    dialogue = [l for l in content.splitlines() if l.startswith("Dialogue:")][0]
    assert "\\N" in dialogue
    lines = dialogue.split("Sub,,0,0,0,,", 1)[1].split("\\N")
    assert len(lines) == 3
    assert all(0 < len(line) <= 10 for line in lines)
    assert "".join(lines) == long_text  # 内容零丢失
    assert not lines[1].startswith("，")  # 行首避标点


def test_wrap_pullup_never_empties_text():
    """回归：11 字句（每行 10 字 + 尾句号）曾把标点挪上行后误清空整行，
    字幕变成空气（sum_001 现场）。折行后文本必须零丢失。"""
    from md2video.assembler.subtitles import _wrap_cjk_text

    wrapped = _wrap_cjk_text("单位圆上，一个点转圈。", 480, 38)
    assert wrapped == "单位圆上，一个点转圈。"  # 挪上行后恰好一行，无 \N
    assert _wrap_cjk_text("公式背了又忘？今天不背公式，只看一张图。", 480, 38).count("\\N") == 1


def test_escape_filter_path_windows_drive():
    assert escape_filter_path("C:\\run\\subtitles.ass") == "C\\:/run/subtitles.ass"
    assert escape_filter_path("artifacts/runs/x/subs.ass") == "artifacts/runs/x/subs.ass"


@pytest.fixture()
def _tiny_video(tmp_path: Path) -> Path:
    src = tmp_path / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x568:rate=30:duration=4", "-c:v", "libx264",
         str(src)],
        check=True, capture_output=True,
    )
    return src


def test_real_ffmpeg_burns_subtitle_pixels(tmp_path: Path, _tiny_video: Path):
    """真 ffmpeg：字幕时段与无字幕时段的底部画面必须不同（像素级验证）。

    片长取 4s（loudnorm 需要 >=3s 音频，见 TODO Maintenance 已知边界）。"""
    entries = [{"segment_id": "s1", "text": "烧录字幕验收", "start": 0.3, "end": 1.2}]
    ass_path = build_ass_file(entries, 320, 568, tmp_path / "subs.ass")
    out = tmp_path / "out.mp4"
    build_and_run_ffmpeg(
        _tiny_video, [], [], base_has_audio=False, out_path=out,
        video_duration=4.0, video_width=320, video_height=568,
        subtitle_filter=f"subtitles=filename='{escape_filter_path(ass_path)}'",
    )
    assert out.is_file()

    from PIL import Image

    def _frame(seconds: float) -> Image.Image:
        target = tmp_path / f"frame_{seconds}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds}",
             "-i", str(out), "-frames:v", "1", str(target)],
            check=True, capture_output=True,
        )
        return Image.open(target).convert("L")

    during = _frame(0.7).crop((40, 480, 280, 560))  # 字幕区（底部中央）
    after = _frame(3.8).crop((40, 480, 280, 560))  # 字幕已消失
    assert list(during.getdata()) != list(after.getdata())
