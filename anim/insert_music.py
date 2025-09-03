import argparse
import json
import subprocess
import shutil
import tempfile
from pathlib import Path
import sys
from typing import List, Dict, Any
import re

# 导入解析器和标记解析函数
from md_parser import parse_markdown_file, _parse_music_marker

# ---------- ffmpeg helpers ----------
def run(cmd, check=True):
    print("RUN:", " ".join(cmd))
    return subprocess.run(cmd, check=check)

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

def detect_leading_silence(src: Path, noise_db: int = -50, dur: float = 0.5) -> float:
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(src),
        "-af", f"silencedetect=noise={noise_db}dB:d={dur}",
        "-f", "null", "-"
    ]
    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    stderr = p.stderr or ""
    m = re.search(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)", stderr)
    if m:
        try:
            t = float(m.group(1))
            return t if t > 0.01 else 0.0
        except Exception:
            return 0.0
    return 0.0

def prepare_audio_segment(src: Path, duration: float, out_path: Path, trim_silence: bool = True, fade_in: float = 2.0):
    use_src = src
    tmp_trim = None
    if trim_silence:
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_trim = Path(tmpf.name)
        tmpf.close()
        cmd_trim = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-af", "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB",
            "-ac", "2", "-ar", "44100", "-vn",
            str(tmp_trim)
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

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(use_src),
        "-t", f"{duration:.3f}",
        "-ac", "2", "-ar", "44100", "-vn"
    ]
    if af_chain:
        cmd.extend(["-af", af_chain])
    cmd.append(str(out_path))
    run(cmd)

    if tmp_trim and tmp_trim.exists():
        try:
            tmp_trim.unlink()
        except Exception:
            pass

def build_and_run_ffmpeg_mix(video_path: Path, music_segments, base_has_audio: bool, out_path: Path, video_duration: float, gain: float = None):
    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    added_lavfi = False
    if not base_has_audio:
        cmd.extend(["-f", "lavfi", "-t", f"{video_duration:.3f}", "-i", f"anullsrc=cl=stereo:r=44100"])
        added_lavfi = True

    for seg in music_segments:
        cmd.extend(["-i", str(seg["path"])])

    parts = []
    if base_has_audio:
        base_label = "[0:a]"
        next_input_idx = 1
    else:
        base_label = "[1:a]"
        next_input_idx = 2

    music_labels = []
    for i, seg in enumerate(music_segments):
        input_idx = next_input_idx + i
        start_ms = int(round(seg["start"] * 1000))
        vol = seg.get("volume", 1.0)
        label = f"[m{i}]"
        parts.append(f"[{input_idx}:a]adelay={start_ms}:all=1,volume={vol}{label}")
        music_labels.append(label)

    all_inputs = [base_label] + music_labels
    amix_inputs = len(all_inputs)
    amix_part = "".join(all_inputs) + f"amix=inputs={amix_inputs}:duration=longest:dropout_transition=0[aout]"

    # 如果用户指定了 gain，就直接放大；否则用 loudnorm 自动响度归一化
    if gain:
        filter_complex = ";".join(parts + [amix_part, f"[aout]volume={gain}[aout]"])
    else:
        filter_complex = ";".join(parts + [amix_part, "[aout]loudnorm[aout]"])

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out_path)])
    run(cmd)

# ---------- mapping parser -> timeline ----------
# （保持你原来的 build_sequence_from_parser 和 map_music_times，不变）

def build_sequence_from_parser(sections: Dict[str, Any]) -> List[Dict[str,Any]]:
    seq = []
    for content in sections.get("contents", []):
        h3 = content.get("h3")
        if h3:
            seq.append({"type":"text","text": h3})
        for para in content.get("text", []):
            for s in para:
                mk = _parse_music_marker(s)
                if mk:
                    kind, name = mk
                    seq.append({"type":"marker","kind": kind, "name": name, "raw": s})
                else:
                    seq.append({"type":"text","text": s})
    for a in sections.get("appendix", []):
        mk = _parse_music_marker(a)
        if mk:
            kind, name = mk
            seq.append({"type":"marker", "kind": kind, "name": name, "raw": a})
        else:
            seq.append({"type":"text", "text": a})
    return seq

def map_music_times(parser_seq: List[Dict[str,Any]], timeline_texts: List[Dict[str,Any]], music_map: Dict[str,str]):
    music_entries = []
    t_idx = 0
    last_text_entry = None
    def find_next_timeline_for(parser_text, start_idx):
        for i in range(start_idx, len(timeline_texts)):
            if timeline_texts[i].get("text") == parser_text:
                return i
        return None
    for i, item in enumerate(parser_seq):
        if item["type"] == "text":
            found_idx = find_next_timeline_for(item["text"], t_idx)
            if found_idx is None:
                found_idx = find_next_timeline_for(item["text"].strip(), t_idx)
            if found_idx is None:
                continue
            last_text_entry = timeline_texts[found_idx]
            t_idx = found_idx + 1
        else:
            kind = item["kind"]
            name = item["name"]
            src = music_map.get(name)
            if kind == "start":
                start_time = None
                for j in range(i+1, len(parser_seq)):
                    if parser_seq[j]["type"] == "text":
                        idx = find_next_timeline_for(parser_seq[j]["text"], t_idx)
                        if idx is None:
                            idx = find_next_timeline_for(parser_seq[j]["text"].strip(), t_idx)
                        if idx is not None:
                            start_time = timeline_texts[idx].get("start")
                        break
                if start_time is None:
                    start_time = (last_text_entry.get("start") if last_text_entry else 0.0)
                music_entries.append({"music": name, "src": src, "start": float(start_time), "end": None})
            else:
                end_time = None
                if last_text_entry:
                    end_time = last_text_entry.get("end")
                if end_time is None:
                    for j in range(i+1, len(parser_seq)):
                        if parser_seq[j]["type"] == "text":
                            idx = find_next_timeline_for(parser_seq[j]["text"], t_idx)
                            if idx is not None:
                                end_time = timeline_texts[idx].get("start")
                                break
                for me in reversed(music_entries):
                    if me["music"] == name and me.get("end") is None:
                        me["end"] = float(end_time) if end_time is not None else me["start"]
                        break
    return music_entries

# ---------- main ----------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("-v","--video", required=True)
    p.add_argument("--bg-scale", type=float, default=0.2)
    p.add_argument("-t","--timeline", required=True)
    p.add_argument("-m","--md", required=True)
    p.add_argument("-o","--out", required=True)
    p.add_argument("--vol", type=float, default=0.8)
    p.add_argument("--fade", type=float, default=2.0)
    p.add_argument("--trim-silence", action="store_true")
    p.add_argument("--gain", type=float, help="手动增益倍数（例如 1.5）。若不指定，则使用 loudnorm 自动归一化")
    args = p.parse_args()

    video_path = Path(args.video)
    timeline_path = Path(args.timeline)
    md_path = Path(args.md)
    out_path = Path(args.out)

    if not video_path.exists() or not timeline_path.exists() or not md_path.exists():
        print("检查路径是否存在")
        sys.exit(1)

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline_texts = [it for it in timeline if "text" in it]

    sections = parse_markdown_file(str(md_path))
    music_map = sections.get("music", {})

    appendix_texts = sections.get("appendix", [])
    appendix_start_time = None
    if appendix_texts:
        starts = []
        for a in appendix_texts:
            for it in timeline_texts:
                if it.get("text") == a and it.get("start") is not None:
                    starts.append(it.get("start"))
        if starts:
            appendix_start_time = min(starts)
    if appendix_start_time is not None:
        print(f"Appendix starts at {appendix_start_time:.3f}s")
    parser_seq = build_sequence_from_parser(sections)
    music_entries = map_music_times(parser_seq, timeline_texts, music_map)
    video_duration = ffprobe_duration(video_path)
    base_has_audio = has_audio_stream(video_path)

    if music_entries:
        print("Detected music entries:")
        for me in music_entries:
            start = float(me.get("start", 0.0))
            end = me.get("end")
            if end is None:
                end_resolved = video_duration
                end_note = "(to video end)"
            else:
                end_resolved = float(end)
                end_note = ""
            src = me.get("src")
            print(f"  - {me.get('music')!r}: start={start:.3f}s  end={end_resolved:.3f}s {end_note}  src={src}")
    else:
        print("没有在 markdown 中发现音乐标记，直接复制视频")
        shutil.copy(video_path, out_path)
        return

    tmpdir = Path(tempfile.mkdtemp(prefix="md2vid_music_"))
    try:
        prepared = []
        for i, m in enumerate(music_entries):
            name = m.get("music")
            src = m.get("src")
            if not src:
                print(f"music {name} no src, skipping")
                continue
            src_path = (Path.cwd() / src).resolve() if not Path(src).is_absolute() else Path(src)
            if not src_path.exists():
                print("music file not found:", src_path, "— skipping")
                continue
            start = float(m.get("start", 0.0))
            end = m.get("end")
            if end is None:
                end = video_duration
            dur = max(0.0, float(end) - float(start))
            if dur <= 0:
                print(f"music {name} non-positive dur, skipping")
                continue
            tmp_out = tmpdir / f"music_{i}.wav"
            print(f"prepare {name}: {src_path} -> {tmp_out} duration={dur:.3f}s start={start:.3f}")
            prepare_audio_segment(src_path, dur, tmp_out, trim_silence=args.trim_silence, fade_in=args.fade)
            is_appendix = (appendix_start_time is not None and start >= appendix_start_time)
            vol = args.vol if is_appendix else max(0.0, args.vol * args.bg_scale)
            prepared.append({"path": tmp_out, "start": start, "volume": vol})
            print(f"  -> {'APPENDIX' if is_appendix else 'BACKGROUND'} music {name}: volume={vol:.3f}")

        if not prepared:
            print("no prepared segments, copying")
            shutil.copy(video_path, out_path)
            return

        build_and_run_ffmpeg_mix(video_path, prepared, base_has_audio, out_path, video_duration, gain=args.gain)
        print("done ->", out_path)
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

if __name__ == "__main__":
    main()
