from __future__ import annotations

import asyncio
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from edge_tts import Communicate

from md2video.tools.cache import ToolCache


class EdgeTTSTool:
    """独立的 TTS 工具，不依赖 manim-voiceover。"""

    def __init__(self, cache_dir: str | Path = "artifacts/tts", voice: str = "zh-CN-YunxiNeural"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice
        self._cache = ToolCache(cache_dir)

    # --- Tool Protocol conformance ---

    @property
    def tool_type(self) -> str:
        return "tts"

    @property
    def provider_name(self) -> str:
        return "edge-tts"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tool Protocol: JSON input -> JSON output。"""
        return self.synthesize(
            text=input_data["text"],
            voice=input_data.get("voice"),
            speed=input_data.get("speed", 1.0),
            fmt=input_data.get("format", "wav"),
        )

    # --- Core logic ---

    def synthesize(self, text: str, voice: Optional[str] = None,
                   speed: float = 1.0, fmt: str = "wav") -> dict:
        """
        合成语音并返回标准结果。
        返回: {"path": str, "duration": float, "provider": str, "cache_key": str}
        """
        voice = voice or self.voice
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("TTS speed must be a finite positive number")
        if fmt not in ("wav", "mp3"):
            raise ValueError(f"Unsupported TTS format {fmt!r}; use 'wav' or 'mp3'")
        params = {"text": text, "voice": voice, "speed": speed}
        cache_key = self._cache.make_key("tts", params)
        output_file = self.cache_dir / f"{cache_key}.{fmt}"

        if not output_file.exists():
            # Edge TTS 永远返回 MP3。下载失败不得留下可命中的半截缓存；
            # 请求 WAV 时做真实转换，再原子发布到旧的缓存键路径。
            with tempfile.TemporaryDirectory(prefix=".tts-", dir=self.cache_dir) as tmp:
                downloaded = Path(tmp) / "download.mp3"
                rate_str = f"{round((speed - 1) * 100):+d}%"
                comm = Communicate(text=text, voice=voice, rate=rate_str)
                asyncio.run(comm.save(str(downloaded)))
                if fmt == "wav":
                    self._write_wav(downloaded, output_file)
                else:
                    downloaded.replace(output_file)
        elif fmt == "wav":
            with output_file.open("rb") as audio:
                header = audio.read(12)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                # 旧版本把 MP3 字节存成 .wav；本地修复，不重新请求语音。
                self._write_wav(output_file, output_file)

        duration = self._get_duration(output_file)
        return {
            "path": str(output_file),
            "duration": duration,
            "provider": "edge-tts",
            "cache_key": cache_key,
        }

    def _write_wav(self, source: Path, target: Path) -> None:
        """转换成功才替换缓存；失败时保留原文件并清理临时产物。"""
        with tempfile.TemporaryDirectory(prefix=".tts-", dir=self.cache_dir) as tmp:
            converted = Path(tmp) / "audio.wav"
            proc = subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-i", str(source),
                "-vn", "-c:a", "pcm_s16le", str(converted),
            ], capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg WAV conversion failed: {proc.stderr.strip()}")
            converted.replace(target)

    def _get_duration(self, audio_path: Path) -> float:
        """用 ffprobe 获取音频时长。"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {audio_path}: {result.stderr.strip()}")
        try:
            duration = float(result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(f"Invalid audio duration for {audio_path}: {result.stdout!r}") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError(f"Invalid audio duration for {audio_path}: {duration}")
        return duration
