# Phase 1: Manifest 驱动的流水线重构

**日期**: 2026-03-31
**状态**: 已完成，端到端验证通过

## 概述

将原有的单体 `anim/` 代码重构为分层模块化的 `md2video/` 包，实现 Manifest 驱动的流水线。功能与原有 `manim -pql main.py Demo` 等价。

## 设计决策

| 决策项 | 选择 | 原因 |
|--------|------|------|
| TTS 解耦方案 | 两阶段（预生成 + CachedVoiceService） | TTS 完全独立于 Manim，可缓存、可替换 |
| 数据模型 | Pydantic | Phase 3 LLM Planner 需要强 schema 校验，一步到位 |
| 旧代码处理 | anim/ 保留不动 | 作为参考，新代码在 md2video/ |
| Python 环境 | 系统Python + typing_extensions 升级 | 解决 manim 导入问题 |

## 新增文件

```
md2video/
    __init__.py
    __main__.py
    config.py
    cli.py
    manifest/
        __init__.py
        schema.py
    parser/
        __init__.py
        segmenter.py
        md_parser.py
    tools/
        __init__.py
        tts/
            __init__.py
            edge_tts.py
        render/
            __init__.py
            cached_voice.py
            manim_renderer.py
    assembler/
        __init__.py
        ffmpeg_assembler.py
    core/
        __init__.py
        pipeline.py
        planner/
            __init__.py
            rule_planner.py
```

## 修改文件

- `.gitignore`: 添加 `artifacts/`、`__pycache__/`、`*.pyc`
- `CLAUDE.md`: 更新为新架构文档
- `run.bat`: 新增系统 Python 调用脚本

## 架构变化

### 旧架构 (anim/)

```
example.md → md_parser.py → main.py (解析+TTS+渲染一体)
                                → timeline.json
                                → insert_media.py (重新解析 markdown)
                                    → output.mp4
```

### 新架构 (md2video/)

```
example.md → Parser → PlanManifest → Planner → TTS Tool → ResultManifest
                                                        → Manim Renderer (CachedVoiceService)
                                                            → FFmpeg Assembler
                                                                → output.mp4
```

关键改进：
- **Manifest 是唯一数据流**：不再重新解析 markdown
- **TTS 独立于 Manim**：通过 CachedVoiceService 桥接
- **工具接口标准化**：固定输入 → 固定输出 + 产物文件

---

## Step 1: Manifest Schema (Pydantic)

**文件**: `md2video/manifest/schema.py`

使用 Pydantic v2 定义了 Plan Manifest 和 Result Manifest 两套数据模型。

### Plan Manifest（执行前 - 描述"要做什么"）

- `AudioRequest`: voice, speed, format
- `SegmentPlan`: id, text, segment_type, visual_type, visual_params, audio_request, explicit, section_context, marker_data
- `PlanManifest`: version, segments[], media_declarations

segment_type 类型：`title_main`, `title_sub`, `section_header`, `content`, `appendix`, `marker_music`, `marker_image`

### Result Manifest（执行后 - 描述"已做出什么"）

- `AudioResult`: path, duration, provider, cache_key
- `VisualResult`: path, width, height, source
- `SegmentResult`: id, audio, visual, start, end
- `ResultManifest`: segments[]

验证：创建/序列化/反序列化、JSON 输出均通过。

---

## Step 2: Parser 适配

**文件**: `md2video/parser/segmenter.py`, `md2video/parser/md_parser.py`

从 `anim/md_parser.py` 拆分为两个模块：

### segmenter.py
- `custom_sentence_split(text, max_len)`: 中文分句逻辑，原样保留
- `_is_declaration_or_marker(text)`: 判断是否为声明/标记

### md_parser.py
- 保留所有解析函数，逻辑与原版一致
- **新增**: `parse_to_plan_manifest(md_path) -> PlanManifest`
  - 将嵌套 dict 结构转换为扁平的 `SegmentPlan` 列表
  - 自动分配 `seg_001`, `seg_002`, ... ID
  - 根据 h1/h2/h3/正文/标记 设置 segment_type
  - 所有文本 segment 默认带 AudioRequest，标记类型带 marker_data

验证：`example.md` 解析为 24 个 segments，类型正确，music 声明正确提取。

---

## Step 3: 独立 TTS Tool

**文件**: `md2video/tools/tts/edge_tts.py`

独立的 edge-tts 调用工具，不依赖 manim-voiceover。

### EdgeTTSTool 类

- `synthesize(text, voice, speed, fmt) -> dict`: 核心方法
  - 返回 `{"path": str, "duration": float, "provider": str, "cache_key": str}`
  - 缓存键: `md5(text|voice|speed)`，缓存目录: `artifacts/tts/`
  - 使用 `asyncio.run()` 调用 edge-tts，`ffprobe` 获取时长
  - 已有缓存时直接返回

### 与原版对比

| | 原 `edge_tts_voice.py` | 新 `EdgeTTSTool` |
|--|--|--|
| 依赖 | manim_voiceover.VoiceService | 无第三方框架依赖 |
| 缓存键 | `hash(text)` | `md5(text|voice|speed)` |
| 输出 | `{final_audio: filename}` | `{path, duration, provider, cache_key}` |

验证：合成 "测试" -> duration=1.54s，二次调用命中缓存。

---

## Step 4: Rule Planner (stub)

**文件**: `md2video/core/planner/rule_planner.py`

Phase 1 的最小 Planner 实现。`plan(segments)` 将所有 `explicit=False` 的 segment 设为 `visual_type="text_only"`。接口为 Phase 2 扩展预留。

验证：24 个 segments 全部 text_only。

---

## Step 5: CachedVoiceService (桥接)

**文件**: `md2video/tools/render/cached_voice.py`

解决 Manim VoiceoverScene 与预生成 TTS 音频之间的桥接问题。不继承 VoiceService，但实现相同的 `_wrap_generate_from_text(text)` 接口约定。

**工作方式**:
1. 构造时接收 `ResultManifest`，构建 segment 索引
2. 每次被 voiceover() 调用时，按顺序返回下一个有音频的 segment 的预生成路径
3. 跳过无音频的 segment（如 marker 类型）
4. `_resolve_path()` 处理路径问题：TTS 路径相对项目根目录，Manim 从 anim/ 运行，依次尝试绝对路径 -> project_root -> cwd.parent

验证：4 个 segment（含 1 个无音频 marker）-> 3 次 voiceover 调用正确返回。

---

## Step 6: Manim Renderer

**文件**: `md2video/tools/render/manim_renderer.py`

从 `anim/main.py` 的 `Demo.construct()` 移植渲染逻辑，改为消费 PlanManifest + ResultManifest。

### ManifestDrivenScene 类

1. 加载 Manifest（从 `artifacts/plan.json` 和 `result.json`）
2. 设置 CachedVoiceService
3. 标题渲染（h1 + h2 Write 动画）
4. 点动画（Lissajous 曲线双点，与原版一致）
5. 内容循环：section_header 左侧小标题、marker_image 点位移、content/appendix 右侧文字+voiceover
6. 收尾 FadeOut，保存 timeline.json

与原 Demo 的区别：不解析 markdown、不生成 TTS、使用 config.py 常量（修复了原版 `DEFAULT_DOTS_OFFSET`/`IMAGE_DOTS_OFFSET` 未定义的 bug）。

验证：67 个动画播放完成，生成 72.87s MP4，timeline.json 22 条记录。

---

## Step 7: FFmpeg Assembler

**文件**: `md2video/assembler/ffmpeg_assembler.py`

从 `anim/insert_media.py` 重构，改为消费 Result Manifest + Plan Manifest。

### 关键变化

| 原版 | 新版 |
|--|--|
| 重新解析 markdown | 直接消费 PlanManifest |
| `build_sequence_from_parser()` 构建事件序列 | segment 列表本身就是序列 |
| `map_entries()` 文本匹配找时间戳 | 直接读 ResultManifest 的 start/end |

### 新增函数

- `extract_music_entries(plan, result)`: 从 manifest 提取音乐时间条目
- `extract_image_entries(plan, result)`: 从 manifest 提取图片时间条目

### Bug 修复

原版 `[0:v]` label 在 filter_complex 中未使用时报错。新版根据是否有视频 filter 决定使用 `0:v`（直接流）还是 `[label]`（filter 输出），处理了有/无音乐、有/无图片的组合情况。

验证：音乐条目正确提取（start=42.46s, end=46.99s），ffmpeg 合成成功。

---

## Step 8: Pipeline Core

**文件**: `md2video/core/pipeline.py`

框架核心编排器。`Pipeline.run(md_path, output_path)` 执行 5 个步骤：

1. **Parse**: `parse_to_plan_manifest()` -> 保存 `artifacts/plan.json`
2. **TTS**: 遍历 segments，`EdgeTTSTool.synthesize()` -> 构建 ResultManifest -> 保存 `artifacts/result.json`
3. **Render**: 复制 renderer 到 anim/，subprocess 调用 manim（设置 PYTHONPATH + 环境变量透传）
4. **Find**: 在 anim/media/ 找到最新 MP4
5. **Assemble**: `FFmpegAssembler.assemble()` 输出最终视频

跨目录运行：Pipeline 从项目根运行，Manim 从 anim/ 运行，通过 PYTHONPATH 和环境变量解决。

---

## Step 9: CLI 入口与配置

**文件**: `md2video/cli.py`, `md2video/__main__.py`, `md2video/config.py`

CLI: `python -m md2video <input.md> [-o output.mp4] [--voice VOICE] [--speed SPEED]`

config.py 集中管理常量（布局坐标、帧率、分辨率、字体等），修复了原版 `DEFAULT_DOTS_OFFSET`/`IMAGE_DOTS_OFFSET` 未定义的 bug。

---

## Step 10: 收尾

### 环境修复

系统 Python 的 `typing_extensions` 4.8.0 太旧，manim 无法导入。升级到 4.15.0，新装 pydantic 2.12.5。修复后 manim 0.19.0、manim_voiceover、edge_tts 7.2.3 全部正常。

### 文件更新

- `.gitignore`: 添加 `artifacts/`、`__pycache__/`
- `CLAUDE.md`: 重写为新架构文档
- `run.bat`: 新增系统 Python 调用脚本

---

## 端到端验证

```bash
python -m md2video anim/example.md -o artifacts/output.mp4
```

| 步骤 | 结果 | 详情 |
|------|------|------|
| [1/5] Parse | 通过 | 24 segments |
| [2/5] TTS | 通过 | 22 audio segments, 总时长 47.0s |
| [3/5] Render | 通过 | 67 animations, 72.87s 视频 |
| [4/5] Find | 通过 | ManifestDrivenScene.mp4 |
| [5/5] Assemble | 通过 | artifacts/output.mp4 (1521 KiB) |

### 已知限制

1. music.mp3 未在 anim/ 目录时正确跳过
2. manim.cfg 位于 anim/，Manim 必须从 anim/ 运行
3. 系统需设置 ffmpeg 在 PATH 中
