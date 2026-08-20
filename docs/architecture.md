# Architecture Notes

本文件保存项目架构说明。可执行路线图见 `TODO.md`。

## 定位

`markdown2video` 是一个 Markdown-first 的视频编译底座。

它应该接收 Markdown，生成结构化 Manifest，调用稳定工具，最后拼出可复现的视频。LLM Planner 可以帮助选择视觉类型，但框架不应该依赖一个自由发挥的 agent 去决定最终布局或剪辑审美。

## Pipeline

```text
Markdown
  -> Parser
  -> Segmenter
  -> Planner
  -> Plan Manifest
  -> TTS / Visual Tools
  -> Execution Assets
  -> Manim Renderer
  -> Timeline
  -> FFmpeg Assembler
  -> Final Result Manifest
  -> MP4
```

## 核心数据模型

- `Segment`：最小时间单元，通常是一句话。TTS 在这个层级执行。
- `Shot`：最小连续视觉单元。一个 shot 包含一个或多个连续 segment，并有目标时长。
- `Scene`：语义或风格分组。一个 scene 可以包含多个共享视觉方案的 shot。

Manifest 是 Planner、Tool、Renderer、Assembler 之间唯一的数据流。工具之间不应该直接通信。

## Runtime Artifacts

每次执行会产生四类主要 artifact：

- `plan.json`：计划和目标约束，描述 segments、scenes、shots、visual intent 和 target duration。
- `execution-assets.json`：素材事实，记录 TTS 音频路径/时长、图片路径/尺寸、provider 和 cache key。
- `timeline.json`：renderer 实际输出的时间事实；text/shot 使用 `start/end`，marker 使用 `time`。
- `result.json`：最终交付摘要，只在 assemble 完成后写出，记录 output MP4、used assets、warnings 和 artifact index。

`result.json` 不应该承担中间执行状态；renderer 和 assembler 应该显式消费 plan、execution assets 和 timeline。

## Planner

Planner 接收 segments，输出 scenes/shots 和视觉决策。

当前有两种 Planner：

- Rule Planner：确定性 fallback，不需要 API key。
- LLM Planner：可选语义规划器，输出必须经过 schema 校验。

框架只消费 Planner 输出，不关心这个输出来自规则还是 LLM。

## Tools

Tool 是可替换执行器，契约固定：

```text
JSON input -> execution -> JSON output + artifact files
```

当前工具类别：

- TTS tools。
- Image tools。
- Render tools。

Tool 选择由 `visual_type`、provider name 和配置优先级决定。LLM 可以建议 `preferred_provider`，但用户配置和工具优先级是兜底依据。

## Visual 与 Layout

项目应该拆开两个决定：

- `visual_type`：用什么素材或工具，例如 text、stock image、local image、video；Manim 是 `render/manim` backend，不是 visual provider。
- `layout_type`：这些素材、文字、字幕放在屏幕哪里。

当前 layout 契约是 scene 级别，`SegmentPlan` 保留同名字段用于兼容 explicit segment 的继承和回填。内置模板包括：

- `center_title_body`
- `full_bleed_image_caption_bottom`
- `image_top_text_bottom`

Agent 只能从有限 layout template 和参数中选择，不应该自由摆像素。Layout 参数由模板自己的 Pydantic schema 校验；runtime 在执行 TTS、渲染和合成前先校验 `layout_type` / `layout_params`。Phase 5.5 只保证 Manifest 契约、layout 计算和校验成立；Manim / FFmpeg 真正消费同一套 layout 是 Phase 6 的目标。

## 时长

TTS 是主时间轴。

每个 segment 有语音时长。Shot 时长由内部 segments 累加得出。视觉工具和渲染器应该适配 shot 时长，而不是截断语音内容。

## 合成

FFmpeg 是最终合成器。它消费 plan、execution assets 和 renderer timeline：

- base video；
- TTS audio；
- background music；
- per-shot visual overlay；
- 支持后再处理 subtitles 或 markers。

## 底座与工作流

Phase 1-7 主要是在做底座：数据结构、工具、布局、渲染、可检查中间产物。

未来 agent 工作流层可以在这个底座之上加入 Codex skill、预览/审核、局部重生成、eval、人工验收等能力。这一层不应该混进近期 runtime 任务。
