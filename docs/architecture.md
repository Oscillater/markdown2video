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

## 编译后端视角

本项目更接近一个视频编译后端，而不是自由发挥的视频 agent。每一层只回答自己负责的问题：

```text
Markdown source
  -> Content IR: Segment
  -> Plan IR: Scene / Shot / layout / segment target duration budget
  -> Scheduled Render IR: renderer 内部执行单元和 cue
  -> Runtime Facts: execution-assets.json + timeline.json
  -> Delivery: result.json + MP4
```

- Parser 只把 Markdown 变成内容结构，不决定最终视觉。
- Planner 把内容结构 lower 成 scene/shot/layout/素材意图。
- Tool 只产生素材事实，例如音频文件、图片文件和它们的 duration/尺寸。
- Renderer 执行计划并产出真实时间线。
- Assembler 不重新规划，只按 timeline 把素材对齐到最终视频。

## 核心数据模型

- `Segment`：内容原子，通常是一句话或一个标题。Markdown marker 可以作为 source event 被识别，但进入 renderer contract 前应 lower 到 shot cue/metadata。
- `Shot`：最小连续视觉执行单元。一个 shot 包含一组有序 segment_ids 和 cue，并保持一段连续视觉状态。
- `Scene`：视觉策略组。一个 scene 可以包含多个共享素材策略、layout/template 和风格决策的 shot。

Manifest 是 Planner、Tool、Renderer、Assembler 之间唯一的数据流。工具之间不应该直接通信。

## Runtime Contract

Runtime contract 定义 planner、tools、renderer 和 assembler 对 Manifest 与 runtime artifacts 的共同理解。简言之：`plan.segments` 是内容字典，`scene.shots[].segment_ids` 决定执行顺序，segment/layout/render template 决定 duration 预算，renderer 输出的 `timeline.json` 是最终时间事实。

- `Segment` 是内容原子，不自动等于显示单元、朗读单元和时间单元三合一。一个 segment 可以产生 audio cue、visual cue 或 animation cue，但这些 cue 不必拥有相同生命周期。
- `Segment.target_duration` 是计划预算，不是最终事实。Shot 不拥有长期 duration budget；shot duration 应由内部 segment/cue 的实际执行结果聚合得出。
- `Shot` 是最小连续视觉单元，持有一组有序 `segment_ids`，并携带 marker / media / visual event cue metadata。
- `Scene` 是共享视觉策略、素材策略和 layout/template 决策的 shot 组。scene 可以持有 `visual_type`、`layout_type` 和 `layout_params`，但不决定 segment 顺序。
- Renderer 必须按 `plan.scenes -> scene.shots -> shot.segment_ids` 遍历。`PlanManifest.segments` 只作为按 id 查找的内容字典，不决定渲染顺序。
- 显示和朗读是分开的。`audio_request` 表示文本是否需要朗读；visual/layout/template 逻辑决定画面显示什么、显示多久。
- `section_context` 只是 metadata，用来记录 segment 属于哪个 section。它不是并行显示文本，也不是并行朗读内容。若需要持续显示 section title，应由 layout/render template 显式表达，而不是从 `section_context` 推断。
- Markdown marker 可以先被 parser 识别为事件，但进入 renderer/scheduling 层前必须 lowering 成 shot 上的 marker cue/metadata。marker 不作为正文 segment 渲染、不朗读、不消费 duration。
- duration 分配不是全局固定规则，而是由 segment type 加 layout/render template 共同决定。有声 content 通常跟随 audio duration；静默可见 content/header 使用自身 target budget；marker 默认是 0 duration 的时间点事件；animation duration 必须计入 segment/shot 预算。
- `timeline.json` 是 renderer 输出的最终时间事实。`shots` 是主时间轴，必须由 renderer 显式写出 `start/end`；`text` 是可见文本 cue；`markers` 是时间点事件 cue。
- assembler 以 `timeline.json` 为时间源，但消费前必须校验它覆盖当前 plan 的 shots、可见文本 cue 和 marker cue。缺失、过期或不一致的 timeline 必须 fail fast。

## Runtime Artifacts

每次执行会产生四类主要 artifact：

- `plan.json`：计划和目标约束，描述 segments、scenes、shots、visual intent、layout intent 和 segment target duration budget。
- `execution-assets.json`：素材事实，记录 TTS 音频路径/时长、图片路径/尺寸、provider 和 cache key。
- `timeline.json`：renderer 实际输出的时间事实；shots/text 使用 `start/end`，marker cue 使用 `time`。
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

目标 layout 契约以 scene 决策和 renderer scheduling unit 携带为主；segment 不应该成为长期 layout 决策源。内置模板包括：

- `center_title_body`
- `full_bleed_image_caption_bottom`
- `image_top_text_bottom`

Agent 只能从有限 layout template 和参数中选择，不应该自由摆像素。Layout 参数由模板自己的 Pydantic schema 校验；runtime 在执行 TTS、渲染和合成前先校验 `layout_type` / `layout_params`。

Manim 和 FFmpeg 通过共享的坐标换算层（`layout/mapping.py`）消费同一套 layout，两者对模板的理解来自同一组函数：

- Renderer 用 `shot_layout_context` 把 shot 的模板解析成单位空间的 region 摆放：正文/字幕堆叠落在 body/text/caption region，标题卡片落在 title region，文本按 region 宽度约束缩放。
- Assembler 用 scene layout 的 `image` region 摆放 per-shot visual：Ken Burns cover 整个 region，静态 overlay contain 进 region；无 layout 契约的条目（如 Markdown marker 图片）保持 legacy 定位，因为 marker 时间区间可以跨 shot。
- `timeline.json` 的 shots 条目记录 `layout_type`，供检查和未来 harness 使用。

## 渲染分辨率

画面尺寸由 `md2video/tools/render/manim.cfg` 声明（竖屏 480x854 @30fps）。渲染 backend 不传 Manim 质量旗标：质量预设（如 `-ql`）会把分辨率覆盖成 16:9 横屏，破坏 layout 归一化坐标的前提。

## 时长

目标契约是：计划时长属于 segment，shot 和 scene 时长是聚合值；最终事实属于 renderer timeline。

- `Segment.target_duration` 是计划预算，不是最终事实。
- 有 `audio_request` 的 segment 由音频/voiceover 决定实际朗读时长，视觉显示可以跟随或覆盖，但不能截断语音。
- 没有 `audio_request` 的 silent segment 仍需要 duration；它来自 segment target budget、layout/render template 默认值或显式动画预算。
- marker 是 0 duration 时间点事件。
- `timeline.json` 的 `shots[].start/end` 是 assembler 可信的最终时间事实。

## 合成

FFmpeg 是最终合成器。它消费 plan、execution assets 和 renderer timeline：

- base video；
- TTS audio；
- background music；
- per-shot visual overlay（按 scene 的 LayoutTemplate image region 摆放，无 layout 契约的条目使用 legacy 定位）；
- 支持后再处理 subtitles 或 markers。

## 底座与工作流

Phase 1-7 主要是在做底座：数据结构、工具、布局、渲染、可检查中间产物。

未来 agent 工作流层可以在这个底座之上加入 Codex skill、预览/审核、局部重生成、eval、人工验收等能力。这一层不应该混进近期 runtime 任务。

## 代码索引

本文件讲契约与设计（why/what）；本节是从概念层到代码的索引（where）。改动模块布局时同步更新本表。

| 概念层 | 实现 | 守着它的测试 |
|---|---|---|
| 入口（md / --plan 双入口） | `md2video/cli.py`、`md2video/__main__.py` | `test_pipeline_artifacts.py` |
| 内容解析（segments + 声明/标记） | `parser/md_parser.py`、`parser/segmenter.py` | `test_md_parser.py`、`test_segmenter.py` |
| 数据模型（Segment/Shot/Scene、assets/result） | `manifest/schema.py` | `test_schema.py` |
| 规划（scenes/shots/cues，rule + llm） | `core/planner/rule_planner.py`、`core/planner/llm_planner.py` | `test_rule_planner.py`、`test_llm_planner.py` |
| Layout（模板、注册表、共享坐标换算） | `layout/schema.py`、`layout/templates.py`、`layout/registry.py`、`layout/mapping.py` | `test_layout.py`、`test_layout_mapping.py` |
| 工具（契约、注册、缓存、TTS/图片/渲染实现） | `tools/protocol.py`、`tools/registry.py`、`tools/cache.py`、`tools/tts/`、`tools/image/`、`tools/render/manim_tool.py` | `test_tool_protocol.py`、`test_tool_registry.py`、`test_tool_cache.py`、`test_edge_tts.py`、`test_pexels_image_tool.py`、`test_local_image_tool.py`、`test_manim_tool.py` |
| 编排（五步流水线、fail-fast、降级分发） | `core/pipeline.py` | `test_dispatch.py`、`test_pipeline_artifacts.py` |
| 渲染（shot 级渲染、timeline 事实） | `tools/render/manim_renderer_inputs.py`（纯 helper）、`tools/render/manim_renderer.py`、`tools/render/timeline_builder.py`、`tools/render/manifest_loader.py`、`tools/render/cached_voice.py` | `test_manim_renderer_inputs.py`、`test_renderer_timeline_state.py`、`test_cached_voice.py` |
| 合成（按时间事实混音、region 叠图） | `assembler/ffmpeg_assembler.py` | `test_ffmpeg_extractor.py`、`test_ken_burns.py` |
| 配置（常量、.env 加载） | `config.py` | 随各层测试覆盖 |
| 像素 smoke（端到端落位验证，默认跳过） | `tests/test_render_smoke.py` | `MD2VIDEO_RENDER_SMOKE=1` 触发 |
