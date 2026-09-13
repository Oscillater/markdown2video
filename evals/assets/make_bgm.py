"""生成验收片用的轻氛围垫乐（代码产资产，与 gen_image 同一哲学）。

20 秒无缝循环：A 小调三和弦纯正弦垫（A3/C4/E4 + 低八度 A2），慢颤音周期
整除循环时长，首尾相位连续 → -stream_loop 循环播放无接缝感。确定性合成，
可随时重跑再生。输出 mono 22050Hz 16-bit WAV（体积紧凑，可入库）。

用法：python evals/assets/make_bgm.py [输出路径]
"""
from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 22050
LOOP_SECONDS = 20.0
# 颤音周期整除循环时长 → 循环点无缝
TREMOLO_PERIOD = 10.0
# A 小调垫：A2 A3 C4 E4（频率 Hz）
NOTES = (110.0, 220.0, 261.63, 329.63)
NOTE_GAINS = (0.30, 0.22, 0.16, 0.14)
MASTER_PEAK = 0.32


def synth() -> bytes:
    total = int(SAMPLE_RATE * LOOP_SECONDS)
    frames = bytearray()
    for n in range(total):
        t = n / SAMPLE_RATE
        tremolo = 0.75 + 0.25 * math.sin(2 * math.pi * t / TREMOLO_PERIOD)
        sample = sum(
            gain * math.sin(2 * math.pi * freq * t)
            for freq, gain in zip(NOTES, NOTE_GAINS)
        )
        sample *= tremolo * MASTER_PEAK
        frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
    return bytes(frames)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "bgm_calm_pad.wav"
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(synth())
    print(f"written {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
