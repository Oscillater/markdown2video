"""非 0 起点 image shot 的 FFmpeg overlay / Ken Burns timing 测试。

A1 验收项：overlay 必须严格落在 timeline 记录的 shot 区间内，
起点非 0 时不得提前或延后出现。包含两层：

- filter 字符串层：zoompan 帧数、overlay enable 窗口使用真实 shot 时间。
- 真实 FFmpeg 行为层：合成后的视频在窗口内显示 overlay、窗口外是底片。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

import md2video.assembler.ffmpeg_assembler as ffmpeg_assembler
from md2video.assembler.ffmpeg_assembler import build_and_run_ffmpeg
from md2video.config import KenBurnsConfig

WIDTH, HEIGHT = 480, 854
# 非 0 起点 shot 区间与检测点
START, END = 1.0, 2.5
REGION = {"left": 100, "top": 300, "width": 200, "height": 200}
CENTER = (REGION["left"] + REGION["width"] // 2,
          REGION["top"] + REGION["height"] // 2)


def _run_build(monkeypatch, image_segments, kb_config):
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
        video_width=WIDTH,
        video_height=HEIGHT,
        ken_burns_config=kb_config,
    )
    cmd = captured["cmd"]
    return cmd[cmd.index("-filter_complex") + 1]


class TestNonZeroStartFilterStrings:
    def test_ken_burns_window_and_frame_count(self, monkeypatch):
        img = {
            "name": "shot_002",
            "src": "/tmp/img.jpg",
            "start": 5.0,
            "end": 7.5,
            "region_px": dict(REGION),
        }

        filter_complex = _run_build(monkeypatch, [img], KenBurnsConfig(enabled=True))

        # 2.5s * 30fps = 75 帧 zoompan
        assert "d=75" in filter_complex
        assert "overlay=x='100':y='300':enable='between(t,5.0,7.5)'" in filter_complex

    def test_static_window(self, monkeypatch):
        img = {
            "name": "shot_002",
            "src": "/tmp/img.jpg",
            "start": 5.0,
            "end": 7.5,
            "region_px": dict(REGION),
        }

        filter_complex = _run_build(monkeypatch, [img], KenBurnsConfig(enabled=False))

        assert "overlay=x='100+(200-w)/2':y='300+(200-h)/2'" in filter_complex
        assert "enable='between(t,5.0,7.5)'" in filter_complex


# ========== 真实 FFmpeg 行为层 ==========


def _make_red_image(path: Path) -> None:
    Image.new("RGB", (100, 100), (255, 0, 0)).save(path)


def _make_base_video(path: Path) -> None:
    """黑底 + 正弦音轨的 3.5s 竖屏底片。"""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=black:size={WIDTH}x{HEIGHT}:rate=30:duration=3.5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        check=True, capture_output=True,
    )


def _extract_pixel(video: Path, t: float, out: Path) -> tuple[int, int, int]:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return Image.open(out).convert("RGB").getpixel(CENTER)


def _is_red(pixel) -> bool:
    r, g, b = pixel
    return r > 180 and g < 80 and b < 80


def _is_black(pixel) -> bool:
    r, g, b = pixel
    return r < 60 and g < 60 and b < 60


def _assert_overlay_window(video: Path, tmp_path: Path, frame_name: str) -> None:
    # 窗口外（前）是黑底
    before = _extract_pixel(video, START - 0.5, tmp_path / f"{frame_name}_before.png")
    assert _is_black(before), f"overlay leaked before window: {before}"
    # 窗口内是红色 overlay
    inside = _extract_pixel(video, (START + END) / 2, tmp_path / f"{frame_name}_inside.png")
    assert _is_red(inside), f"overlay missing inside window: {inside}"
    # 窗口外（后）回到黑底
    after = _extract_pixel(video, END + 0.4, tmp_path / f"{frame_name}_after.png")
    assert _is_black(after), f"overlay leaked after window: {after}"


@pytest.mark.parametrize("kb_enabled", [False, True],
                         ids=["static_overlay", "ken_burns"])
def test_overlay_appears_only_inside_non_zero_window(tmp_path, kb_enabled):
    base_path = tmp_path / "base.mp4"
    image_path = tmp_path / "red.png"
    _make_base_video(base_path)
    _make_red_image(image_path)

    entry = {
        "name": "shot_002",
        "src": str(image_path),
        "start": START,
        "end": END,
        "region_px": dict(REGION),
    }

    out_path = tmp_path / "out.mp4"
    build_and_run_ffmpeg(
        video_path=base_path,
        music_segments=[],
        image_segments=[entry],
        base_has_audio=True,
        out_path=out_path,
        video_duration=3.5,
        video_width=WIDTH,
        video_height=HEIGHT,
        ken_burns_config=KenBurnsConfig(enabled=kb_enabled),
    )

    assert out_path.is_file()
    _assert_overlay_window(out_path, tmp_path, f"kb_{kb_enabled}")
