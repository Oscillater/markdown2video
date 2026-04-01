# Phase 1.2: 媒体嵌入修复与完善

**日期**: 2026-04-01
**状态**: 已完成

## 概述

在实际测试图片/音乐嵌入功能时，发现并修复了多个问题：文字在语音播完前消失、manim.cfg 依赖外部目录导致分辨率错误、媒体路径解析不正确、marker 时间轴不同步、附录未分句。

## 修改文件

- `md2video/tools/render/manim_renderer.py`
- `md2video/tools/render/manim.cfg` (新增)
- `md2video/assembler/ffmpeg_assembler.py`
- `md2video/core/pipeline.py`
- `md2video/parser/md_parser.py`

## 新增文件

```
md2video/tools/render/manim.cfg    # 内置 manim 配置（竖屏 480x854）
example/example.md                 # 测试用 markdown 样例（含图片和音乐）
```

---

## Bug 1: 文字在语音播完前消失

**文件**: `md2video/tools/render/manim_renderer.py`

### 现象

每句话 TTS 还没念完，文字就消失了。

### 原因

`self.wait(2)` 和 `self.remove(sentence)` 在 `with self.voiceover(text=line)` 块**内部**执行。`voiceover()` 的 `finally` 块会调用 `wait_for_voiceover()` 等待剩余语音时长，但文字已经在块内被 `remove` 了。对于超过 2 秒的句子，文字在 2 秒后就消失，语音还在继续。

### 修复

将文字创建和显示放在 `voiceover` 块内（确保语音播放时文字可见），将 `wait(2)` 和 `remove` 移到块外（确保语音播完后文字再多停留 2 秒）。

```python
# 修复前
with self.voiceover(text=line) as tracker:
    sentence = textWithFont(...)
    self.add(sentence)
    self.wait(2)
    self.remove(sentence)

# 修复后
sentence = textWithFont(...)
with self.voiceover(text=line) as tracker:
    self.add(sentence)
self.wait(2)
self.remove(sentence)
```

---

## Bug 2: manim.cfg 依赖外部 anim/ 目录

**文件**: `md2video/tools/render/manim.cfg`, `md2video/core/pipeline.py`

### 现象

删除 `anim/` 目录后重新运行 pipeline，生成的视频内容变小，布局错乱。

### 原因

`manim.cfg`（配置竖屏 480x854 分辨率、30fps）原来只存在于 `anim/` 目录。Pipeline 从 `anim/manim.cfg` 复制到渲染工作目录。删除 `anim/` 后复制源不存在，manim 使用默认横屏 854x480，导致竖屏布局的内容被裁切/缩小。

当 `anim/` 存在时，旧版 `manim -ql`（无 `render` 子命令）在 manim v0.19 中会自动从 `anim/` 目录读取 `manim.cfg`，恰好绕过了这个问题。

### 修复

1. 将 `manim.cfg` 内置到 `md2video/tools/render/manim.cfg`
2. Pipeline 从包内复制，不再依赖外部 `anim/` 目录
3. 清理临时文件时同时清理复制的 `manim.cfg`
4. manim 命令使用 `render` 子命令（manim v0.19 规范）

---

## Bug 3: 媒体文件路径解析不正确

**文件**: `md2video/assembler/ffmpeg_assembler.py`, `md2video/core/pipeline.py`

### 现象

图片和音乐均未在最终视频中显示/播放。

### 原因

- **音乐路径**：`Path.cwd() / src` 相对于运行命令时的当前工作目录解析，但媒体文件在 markdown 文件所在目录（如 `example/`）下
- **图片路径**：`Path(img["src"])` 原样传给 ffmpeg，无任何路径解析

当用户从项目根目录运行 `python -m md2video example/example.md` 时，CWD 是根目录，而 `music.mp3` 在 `example/` 下，找不到文件被静默跳过。

### 修复

1. `FFmpegAssembler` 新增 `md_dir` 参数，指定 markdown 文件所在目录
2. 音乐路径：`(self.md_dir / src).resolve()`
3. 图片路径：非绝对路径时 `(self.md_dir / src).resolve()`
4. Pipeline 将 `md_path.parent` 作为 `md_dir` 传入

---

## Bug 4: 图片/音乐时间轴与视频不同步

**文件**: `md2video/tools/render/manim_renderer.py`, `md2video/assembler/ffmpeg_assembler.py`, `md2video/core/pipeline.py`

### 现象

图片在错误的时间点消失，音乐在错误的时间点开始。比如 `[image_end cover]` 标在"人将失之耶"之后，但图片在"人将失之耶"刚念完就消失了；`[music_start bgm]` 标在附录开头，但音乐提前到了前面。

### 原因

Assembler 使用 Result Manifest 中的 TTS 音频时间来定位 marker，但 Manim 渲染时每段 content 额外 `wait(2)`，每段 section_header 额外 `wait(0.5)` + 动画时间。TTS 时间只反映纯音频时长，不包含 Manim 的额外等待。例如 TTS 时间轴上 marker 在 33.8s，但实际视频已经到了 50s+。

### 修复

1. **Manim 渲染器**：处理 marker 时记录 `self.time`（实际视频时间）到 `timeline.json` 的 `markers` 字段
2. **Assembler**：`extract_music_entries` 和 `extract_image_entries` 新增 `timeline_path` 参数，优先从 timeline.json 读取 marker 的实际视频时间，回退到 Result Manifest 的 TTS 时间
3. **Pipeline**：将 `anim_dir / "timeline.json"` 路径传给 Assembler

### timeline.json 格式变化

```json
// 修复前
[{"text": "...", "start": 0, "end": 1.5}, ...]

// 修复后
{
  "text": [{"text": "...", "start": 0, "end": 1.5}, ...],
  "markers": [
    {"id": "seg_006", "segment_type": "marker_image", "kind": "start", "name": "cover", "time": 18.2},
    ...
  ]
}
```

---

## Bug 5: 附录区未分句

**文件**: `md2video/parser/md_parser.py`

### 现象

附录区的长句没有被拆分成短句，整段文字作为单一 segment 由 TTS 一次性念完，画面上也没有逐句显示的效果。

### 原因

内容区（`sections["contents"]`）的每一行会经过 `custom_sentence_split()` 分句后再逐句创建 segment。但附录区（`sections["appendix"]`）的每一行直接整行作为一个 segment，没有调用分句函数。

### 修复

附录区也使用 `custom_sentence_split()` 分句：

```python
# 修复前
segments.append(SegmentPlan(id=next_id(), text=line, segment_type="appendix", ...))

# 修复后
for sentence in custom_sentence_split(line):
    segments.append(SegmentPlan(id=next_id(), text=sentence, segment_type="appendix", ...))
```
