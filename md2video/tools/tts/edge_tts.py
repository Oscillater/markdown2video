from __future__ import annotations

import asyncio
import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from edge_tts import Communicate


class EdgeTTSTool:
    """独立的 TTS 工具，不依赖 manim-voiceover。"""

    def __init__(self, cache_dir: str | Path = "artifacts/tts", voice: str = "zh-CN-YunxiNeural"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice

    def synthesize(self, text: str, voice: Optional[str] = None,
                   speed: float = 1.0, fmt: str = "wav") -> dict:
        """
        合成语音并返回标准结果。
        返回: {"path": str, "duration": float, "provider": str, "cache_key": str}
        """
        voice = voice or self.voice
        cache_key = hashlib.md5(f"{text}|{voice}|{speed}".encode()).hexdigest()
        output_file = self.cache_dir / f"{cache_key}.{fmt}"

        if not output_file.exists():
            rate_str = f"+{int((speed - 1) * 100)}%" if speed != 1.0 else "+0%"
            comm = Communicate(text=text, voice=voice, rate=rate_str)
            asyncio.run(comm.save(str(output_file)))

        duration = self._get_duration(output_file)
        return {
            "path": str(output_file),
            "duration": duration,
            "provider": "edge-tts",
            "cache_key": cache_key,
        }

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
            # fallback: 估算 1 秒
            return 1.0
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 1.0
