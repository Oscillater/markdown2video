# insert_media.py
import argparse
import json
import subprocess
import shutil
import tempfile
from pathlib import Path
import sys
from typing import List, Dict, Any, Tuple
import re

from md_parser import parse_markdown_file, _parse_music_marker

# ---------- ffmpeg helpers ----------
def run(cmd, check=True):
    print("RUN:", " ".join(cmd))
    return subprocess.run(cmd, check=check)

# ✨ 新增：自动检测视频分辨率的函数
def ffprobe_resolution(path: Path) -> Tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed to get resolution: {p.stderr}")
    try:
        width, height = map(int, p.stdout.strip().split('x'))
        return width, height
    except Exception as e:
        raise RuntimeError(f"Could not parse resolution from ffprobe output: {p.stdout.strip()}") from e

def ffprobe_duration(path: Path) -> float:
    # ... (此函数不变)
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    return float(p.stdout.strip())

def has_audio_stream(path: Path) -> bool:
    # ... (此函数不变)
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return bool(p.stdout.strip())

def prepare_audio_segment(src: Path, duration: float, out_path: Path, trim_silence: bool = True, fade_in: float = 2.0):
    # ... (此函数不变)
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
                if tmp_trim.exists(): tmp_trim.unlink()
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

def build_sequence_from_parser(sections: Dict[str, Any]) -> List[Dict[str,Any]]:
    # ... (此函数不变)
    seq = []
    for content in sections.get("contents", []):
        if content.get("h3"):
            seq.append({"type":"text","text": content.get("h3")})
        for para in content.get("text", []):
            for s in para:
                mk = _parse_music_marker(s)
                if mk:
                    kind, name = mk
                    seq.append({"type":"marker","subtype":"music","kind":kind,"name":name,"raw":s})
                elif s.strip().startswith("[image_"):
                    m = re.match(r"\[(image_start|image_end)\s+(\w+)\]", s.strip())
                    if m:
                        kind = "start" if m.group(1) == "image_start" else "end"
                        name = m.group(2)
                        seq.append({"type":"marker","subtype":"image","kind":kind,"name":name,"raw":s})
                    else:
                        seq.append({"type":"text","text": s})
                else:
                    seq.append({"type":"text","text": s})
    for a in sections.get("appendix", []):
        mk = _parse_music_marker(a)
        if mk:
            kind, name = mk
            seq.append({"type":"marker","subtype":"music","kind":kind,"name":name,"raw":a})
        elif a.strip().startswith("[image_"):
            m = re.match(r"\[(image_start|image_end)\s+(\w+)\]", a.strip())
            if m:
                kind = "start" if m.group(1) == "image_start" else "end"
                name = m.group(2)
                seq.append({"type":"marker","subtype":"image","kind":kind,"name":name,"raw":a})
            else:
                seq.append({"type":"text","text": a})
        else:
            seq.append({"type":"text","text": a})
    return seq

def map_entries(parser_seq: List[Dict[str,Any]], timeline_texts: List[Dict[str,Any]], media_map: Dict[str,str], subtype: str):
    # ... (此函数不变)
    entries = []
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
        elif item["type"] == "marker" and item["subtype"] == subtype:
            if item["kind"] == "start":
                start_time = None
                for j in range(i + 1, len(parser_seq)):
                    if parser_seq[j]["type"] == "text":
                        idx = find_next_timeline_for(parser_seq[j]["text"], t_idx)
                        if idx is not None:
                            start_time = timeline_texts[idx].get("start")
                            break
                if start_time is None:
                    start_time = last_text_entry.get("start", 0.0)
                entry = item.copy()
                entry.update({
                    "src": media_map.get(item["name"]),
                    "start": float(start_time),
                    "end": None
                })
                entries.append(entry)
            else: # kind == "end"
                end_time = None
                if last_text_entry:
                    end_time = last_text_entry.get("end")
                if end_time is None:
                    for j in range(i + 1, len(parser_seq)):
                        if parser_seq[j]["type"] == "text":
                            idx = find_next_timeline_for(parser_seq[j]["text"], t_idx)
                            if idx is not None:
                                end_time = timeline_texts[idx].get("start")
                                break
                for me in reversed(entries):
                    if me["name"] == item["name"] and me.get("end") is None:
                        me["end"] = float(end_time) if end_time is not None else me["start"]
                        break
    return entries

# ---------- ffmpeg builder ----------
# ✨ 更新函数签名，接收视频的宽和高
def build_and_run_ffmpeg_mix_and_images(video_path: Path, music_segments, image_segments, base_has_audio: bool, out_path: Path, video_duration: float, video_width: int, video_height: int, gain: float = None):
    
    # --- ✨ 图片位置和大小配置 (使用相对比例，与分辨率无关) ✨ ---
    # 所有图片将被缩放以适应这个边界框，同时保持原始宽高比
    # (数值范围 0.0 到 1.0)
    REL_MAX_WIDTH = 0.6  # 图片最大宽度占视频总宽度的 25%
    REL_MAX_HEIGHT = 0.7 # 图片最大高度占视频总高度的 25%

    # 缩放后的图片将以此为中心点进行放置
    REL_CENTER_X = 0.6   # 中心点 X 坐标在视频总宽度的 85% 处 (右侧)
    REL_CENTER_Y = 0.35   # 中心点 Y 坐标在视频总高度的 20% 处 (上方)
    # --- 结束配置 ---
    
    # ✨ 动态计算绝对像素值
    MAX_WIDTH = int(video_width * REL_MAX_WIDTH)
    MAX_HEIGHT = int(video_height * REL_MAX_HEIGHT)
    CENTER_X = int(video_width * REL_CENTER_X)
    CENTER_Y = int(video_height * REL_CENTER_Y)
    
    # --- 后续逻辑与之前类似，但使用计算出的值 ---
    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if base_has_audio:
        base_label = "[0:a]"
        next_input_idx = 1
    else:
        cmd.extend(["-f", "lavfi", "-t", f"{video_duration:.3f}", "-i", f"anullsrc=cl=stereo:r=44100"])
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
        start_ms, vol = int(round(seg["start"] * 1000)), seg.get("volume", 1.0)
        label = f"[m{i}]"
        audio_parts.append(f"[{input_idx}:a]adelay={start_ms}:all=1,volume={vol}{label}")
        music_labels.append(label)
    
    all_inputs = [base_label] + music_labels
    amix_part = "".join(all_inputs) + f"amix=inputs={len(all_inputs)}:duration=longest:dropout_transition=0[aout]"
    audio_chain = f"[aout]volume={gain}[aout]" if gain else "[aout]loudnorm[aout]"

    video_label = "[0:v]"
    vid_parts = []
    for i, img in enumerate(image_segments):
        img_input_stream = f"[{img_input_base_idx + i}:v]"
        scaled_img_stream = f"[img{i}_scaled]"
        scale_filter = (f"{img_input_stream}scale=w='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),{MAX_WIDTH},-2)':h='if(gt(iw/ih,{MAX_WIDTH}/{MAX_HEIGHT}),-2,{MAX_HEIGHT})',setsar=1{scaled_img_stream}")
        vid_parts.append(scale_filter)
        start = img["start"]
        end = img["end"] if img["end"] is not None else video_duration
        out_label = f"[v{i}]"
        overlay_filter = (f"{video_label}{scaled_img_stream}overlay=x='{CENTER_X}-w/2':y='{CENTER_Y}-h/2':enable='between(t,{start},{end})'{out_label}")
        vid_parts.append(overlay_filter)
        video_label = out_label

    filter_complex = ";".join(audio_parts + [amix_part, audio_chain] + vid_parts)
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", video_label, "-map", "[aout]", "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", str(out_path)])
    run(cmd)

# ---------- main ----------
def main():
    # ... (main 函数的参数解析部分不变)
    p = argparse.ArgumentParser()
    p.add_argument("-v","--video", required=True)
    p.add_argument("-t","--timeline", required=True)
    p.add_argument("-m","--md", required=True)
    p.add_argument("-o","--out", required=True)
    p.add_argument("--bg-scale", type=float, default=0.2)
    p.add_argument("--vol", type=float, default=0.8)
    p.add_argument("--fade", type=float, default=2.0)
    p.add_argument("--trim-silence", action="store_true")
    p.add_argument("--gain", type=float)
    args = p.parse_args()

    video_path = Path(args.video)
    timeline_path = Path(args.timeline)
    md_path = Path(args.md)
    out_path = Path(args.out)

    # ✨ 在主流程中自动获取视频尺寸
    video_width, video_height = ffprobe_resolution(video_path)
    video_duration = ffprobe_duration(video_path)
    print(f"Detected video properties: {video_width}x{video_height}, duration={video_duration:.2f}s")
    
    base_has_audio = has_audio_stream(video_path)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline_texts = [it for it in timeline if "text" in it]
    sections = parse_markdown_file(str(md_path))
    music_map = sections.get("music", {})
    image_map = sections.get("images", {})

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
    music_entries = map_entries(parser_seq, timeline_texts, music_map, "music")
    image_entries = map_entries(parser_seq, timeline_texts, image_map, "image")

    print("Music entries:", music_entries)
    print("Image entries:", image_entries)

    tmpdir = Path(tempfile.mkdtemp(prefix="md2vid_media_"))
    prepared_music, prepared_images = [], []
    try:
        # Music preparation
        for m in music_entries:
            # ... (music preparation logic is unchanged)
            name, src = m.get("name"), m.get("src")
            if not src: continue
            src_path = (Path.cwd() / src).resolve() if not Path(src).is_absolute() else Path(src)
            if not src_path.exists(): continue
            start = float(m["start"])
            end = m["end"] if m["end"] is not None else video_duration
            dur = max(0.0, end - start)
            if dur <= 0: continue
            tmp_out = tmpdir / f"music_{music_entries.index(m)}.wav"
            prepare_audio_segment(src_path, dur, tmp_out, trim_silence=args.trim_silence, fade_in=args.fade)
            is_appendix = (appendix_start_time is not None and start >= appendix_start_time)
            vol = args.vol if is_appendix else max(0.0, args.vol * args.bg_scale)
            prepared_music.append({"path": tmp_out, "start": start, "volume": vol})
        
        # Image preparation
        for img in image_entries:
            src = Path(img["src"])
            if src.exists(): prepared_images.append(img)

        # ✨ 调用时传入自动检测到的视频尺寸
        build_and_run_ffmpeg_mix_and_images(video_path, prepared_music, prepared_images, base_has_audio, out_path, video_duration, video_width, video_height, gain=args.gain)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    main()