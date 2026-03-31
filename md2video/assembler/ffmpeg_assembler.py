"""
FFmpeg Assembler - 消费 Result Manifest + Plan Manifest，合成最终视频。

不再重新解析 markdown，所有数据来自 manifest。
"""
from __future__ import annotations

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple

from md2video.manifest.schema import PlanManifest, ResultManifest


# ========== ffmpeg helpers ==========

def run(cmd, check=True):
    print("RUN:", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def ffprobe_resolution(path: Path) -> Tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    width, height = map(int, p.stdout.strip().split("x"))
    return width, height


def ffprobe_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    return float(p.stdout.strip())


def has_audio_stream(path: Path) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return bool(p.stdout.strip())


def prepare_audio_segment(src: Path, duration: float, out_path: Path,
                          trim_silence: bool = True, fade_in: float = 2.0):
    use_src = src
    tmp_trim = None
    if trim_silence:
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_trim = Path(tmpf.name)
        tmpf.close()
        cmd_trim = [
            "ffmpeg", "-y", "-i", str(src),
            "-af", "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB",
            "-ac", "2", "-ar", "44100", "-vn", str(tmp_trim)
        ]
        run(cmd_trim)
        if tmp_trim.exists() and tmp_trim.stat().st_size > 100:
            use_src = tmp_trim
        else:
            try:
                if tmp_trim.exists():
                    tmp_trim.unlink()
                tmp_trim = None
            except Exception:
                tmp_trim = None

    af_filters = []
    if fade_in and fade_in > 0 and duration > 0:
        fd = min(fade_in, duration)
        af_filters.append(f"afade=t=in:st=0:d={fd:.3f}")

    af_chain = ",".join(af_filters) if af_filters else None
    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(use_src),
           "-t", f"{duration:.3f}", "-ac", "2", "-ar", "44100", "-vn"]
    if af_chain:
        cmd.extend(["-af", af_chain])
    cmd.append(str(out_path))
    run(cmd)

    if tmp_trim and tmp_trim.exists():
        try:
            tmp_trim.unlink()
        except Exception:
            pass


# ========== 从 Manifest 提取媒体时间 ==========

def extract_music_entries(plan: PlanManifest, result: ResultManifest) -> List[Dict]:
    """从 Manifest 中提取音乐时间段。"""
    # 建立 id -> segment 映射
    result_map = {seg.id: seg for seg in result.segments}
    music_map = plan.media_declarations.get("music", {})
    entries = []

    for seg in plan.segments:
        if seg.segment_type != "marker_music" or not seg.marker_data:
            continue
        kind = seg.marker_data["kind"]
        name = seg.marker_data["name"]
        src = music_map.get(name)

        if kind == "start":
            # 找下一个有音频的 segment 的 start time
            start_time = None
            for rseg in result.segments:
                if rseg.id == seg.id:
                    # marker 本身没有 audio，找之后的
                    continue
                # 简化: 用 marker 后面紧邻的 content segment 的 start
                break
            # 更好的方式: 在 result 中找这个 marker 对应的 start
            if seg.id in result_map:
                start_time = result_map[seg.id].start
            if start_time is None:
                start_time = 0.0

            entries.append({
                "name": name,
                "src": src,
                "start": float(start_time),
                "end": None,
            })
        elif kind == "end":
            end_time = None
            if seg.id in result_map:
                end_time = result_map[seg.id].end
            # 回填 start
            for entry in reversed(entries):
                if entry["name"] == name and entry["end"] is None:
                    entry["end"] = float(end_time) if end_time is not None else entry["start"]
                    break

    return entries


def extract_image_entries(plan: PlanManifest, result: ResultManifest) -> List[Dict]:
    """从 Manifest 中提取图片时间段。"""
    result_map = {seg.id: seg for seg in result.segments}
    image_map = plan.media_declarations.get("images", {})
    entries = []

    for seg in plan.segments:
        if seg.segment_type != "marker_image" or not seg.marker_data:
            continue
        kind = seg.marker_data["kind"]
        name = seg.marker_data["name"]
        src = image_map.get(name)

        if kind == "start":
            start_time = result_map[seg.id].start if seg.id in result_map else 0.0
            entries.append({
                "name": name,
                "src": src,
                "start": float(start_time),
                "end": None,
            })
        elif kind == "end":
            end_time = result_map[seg.id].end if seg.id in result_map else None
            for entry in reversed(entries):
                if entry["name"] == name and entry["end"] is None:
                    entry["end"] = float(end_time) if end_time is not None else entry["start"]
                    break

    return entries


# ========== ffmpeg 合成 ==========

def build_and_run_ffmpeg(video_path: Path, music_segments, image_segments,
                         base_has_audio: bool, out_path: Path,
                         video_duration: float, video_width: int, video_height: int,
                         gain: float = None):

    REL_MAX_WIDTH = 0.6
    REL_MAX_HEIGHT = 0.7
    REL_CENTER_X = 0.6
    REL_CENTER_Y = 0.35

    MAX_WIDTH = int(video_width * REL_MAX_WIDTH)
    MAX_HEIGHT = int(video_height * REL_MAX_HEIGHT)
    CENTER_X = int(video_width * REL_CENTER_X)
    CENTER_Y = int(video_height * REL_CENTER_Y)

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if base_has_audio:
        base_label = "[0:a]"
        next_input_idx = 1
    else:
        cmd.extend(["-f", "lavfi", "-t", f"{video_duration:.3f}",
                     "-i", "anullsrc=cl=stereo:r=44100"])
        base_label = "[1:a]"
        next_input_idx = 2

    for seg in music_segments:
        cmd.extend(["-i", str(seg["path"])])
    img_input_base_idx = next_input_idx + len(music_segments)
    for img in image_segments:
        cmd.extend(["-i", str(img["src"])])

    audio_parts, music_labels = [], []
    for i, seg in enumerate(music_segments):
        input_idx = next_input_idx + i
        start_ms = int(round(seg["start"] * 1000))
        vol = seg.get("volume", 1.0)
        label = f"[m{i}]"
        audio_parts.append(f"[{input_idx}:a]adelay={start_ms}:all=1,volume={vol}{label}")
        music_labels.append(label)

    # 构建音频 filter
    audio_filter_parts = []
    audio_map_label = "0:a" if base_has_audio else None
    if music_segments or not base_has_audio:
        all_inputs = [base_label] + music_labels
        amix_part = "".join(all_inputs) + f"amix=inputs={len(all_inputs)}:duration=longest:dropout_transition=0[aout]"
        audio_chain = f"[aout]volume={gain}[aout]" if gain else "[aout]loudnorm[aout]"
        audio_filter_parts = audio_parts + [amix_part, audio_chain]
        audio_map_label = "[aout]"
    else:
        # 已有音频，无音乐，只需 loudnorm
        audio_filter_parts = [f"[0:a]loudnorm[aout]"]
        audio_map_label = "[aout]"

    video_label = "[0:v]"
    vid_parts = []
    for i, img in enumerate(image_segments):
        img_input_stream = f"[{img_input_base_idx + i}:v]"
        scaled_img_stream = f"[img{i}_scaled]"
        scale_filter = (
            f"{img_input_stream}scale=w='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),{MAX_WIDTH},-2)'"
            f":h='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),-2,{MAX_HEIGHT})',setsar=1{scaled_img_stream}"
        )
        vid_parts.append(scale_filter)
        start = img["start"]
        end = img["end"] if img["end"] is not None else video_duration
        out_label = f"[v{i}]"
        overlay_filter = (
            f"{video_label}{scaled_img_stream}"
            f"overlay=x='{CENTER_X}-w/2':y='{CENTER_Y}-h/2':enable='between(t,{start},{end})'{out_label}"
        )
        vid_parts.append(overlay_filter)
        video_label = out_label

    has_filter = audio_filter_parts or vid_parts
    if has_filter:
        filter_parts = audio_filter_parts + vid_parts
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])

    # Video map
    if vid_parts:
        cmd.extend(["-map", video_label])
    else:
        cmd.extend(["-map", "0:v"])

    # Audio map
    cmd.extend(["-map", audio_map_label])
    cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", str(out_path)])
    run(cmd)


# ========== Assembler 主类 ==========

class FFmpegAssembler:
    def __init__(self, plan: PlanManifest, result: ResultManifest,
                 video_path: Path, output_path: Path,
                 bg_scale: float = 0.2, vol: float = 0.8,
                 fade: float = 2.0, trim_silence: bool = False, gain: float = None):
        self.plan = plan
        self.result = result
        self.video_path = video_path
        self.output_path = output_path
        self.bg_scale = bg_scale
        self.vol = vol
        self.fade = fade
        self.trim_silence = trim_silence
        self.gain = gain

    def assemble(self) -> Path:
        video_width, video_height = ffprobe_resolution(self.video_path)
        video_duration = ffprobe_duration(self.video_path)
        base_has_audio = has_audio_stream(self.video_path)
        print(f"Video: {video_width}x{video_height}, duration={video_duration:.2f}s")

        # 提取音乐/图片条目
        music_entries = extract_music_entries(self.plan, self.result)
        image_entries = extract_image_entries(self.plan, self.result)

        print("Music entries:", music_entries)
        print("Image entries:", image_entries)

        # 判断 appendix 起始时间
        appendix_start = None
        for seg in self.plan.segments:
            if seg.segment_type == "appendix":
                # 找到第一个 appendix segment 的 result start time
                for rseg in self.result.segments:
                    if rseg.id == seg.id:
                        appendix_start = rseg.start
                        break
                break

        tmpdir = Path(tempfile.mkdtemp(prefix="md2vid_media_"))
        prepared_music, prepared_images = [], []
        try:
            for m in music_entries:
                name, src = m.get("name"), m.get("src")
                if not src:
                    continue
                src_path = (Path.cwd() / src).resolve() if not Path(src).is_absolute() else Path(src)
                if not src_path.exists():
                    continue
                start = float(m["start"])
                end = m["end"] if m["end"] is not None else video_duration
                dur = max(0.0, end - start)
                if dur <= 0:
                    continue

                tmp_out = tmpdir / f"music_{music_entries.index(m)}.wav"
                prepare_audio_segment(src_path, dur, tmp_out,
                                      trim_silence=self.trim_silence, fade_in=self.fade)

                is_appendix = (appendix_start is not None and start >= appendix_start)
                vol = self.vol if is_appendix else max(0.0, self.vol * self.bg_scale)
                prepared_music.append({"path": tmp_out, "start": start, "volume": vol})

            for img in image_entries:
                src = Path(img["src"])
                if src.exists():
                    prepared_images.append(img)

            build_and_run_ffmpeg(
                self.video_path, prepared_music, prepared_images,
                base_has_audio, self.output_path,
                video_duration, video_width, video_height, gain=self.gain,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return self.output_path
