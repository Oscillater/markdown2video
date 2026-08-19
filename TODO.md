# TODO / Roadmap

本文件只放可执行路线图。架构说明放到 `docs/architecture.md`。

## 项目边界

当前目标：把 `markdown2video` 做成一个可靠的 Markdown-first、Manifest-driven 视频编译器。

更准确地说：近期做的是 **framework/runtime**，不是完整的 agent 产品。

- Markdown 是内容源。
- `PlanManifest` 是要做什么。
- Tool 负责 TTS、图片、渲染、合成等确定性执行。
- Layout Template 负责稳定排版约束。
- Runtime artifacts 记录每次执行的计划、素材、时间线和最终交付。

Runtime artifact 分层约定：

```text
plan.json
= 意图和目标约束：segments / scenes / shots / visual_type / visual_params / layout / target_duration

execution-assets.json
= 素材事实：TTS 音频路径、音频时长、图片路径、图片尺寸、provider、cache key

timeline.json
= 时间事实：renderer 实际输出的字幕、marker、shot 或 segment 时间

result.json
= 最终交付：output MP4、used assets、warnings、artifact index
```

未来的 **harness/workflow** 单独放到后面：agent 读需求、编辑 Manifest、预览审核、人工替换图片、局部重跑、eval 和人工验收。

核心边界：

```text
Markdown / user intent
        ↓
Planner or harness produces PlanManifest
        ↓
framework/runtime executes PlanManifest
        ↓
execution-assets + timeline + result + MP4
        ↓
future harness preview/review/partial rerun
```

近期不做：

- 不做通用 AI 视频生成器。
- 不让 agent 自由当剪辑师。
- 不把完整 preview/review 工作流塞进当前 runtime。
- 不把 AI 视频、AI 音乐、世界模型视频当成近期主线。

## 当前状态

- Phase 1-4 已完成。
- 当前处在 Phase 5。
- 最新验证：2026-08-19 运行 `PYTHON_DOTENV_DISABLED=1 python -m pytest -q`，结果是 `267 passed, 5 warnings`。
- 已有旧的 Markdown -> MP4 流程：`python -m md2video example/example.md -o artifacts/output.mp4`。
- 旧流程可以用 Markdown 显式图片标记 `[image_start]` / `[image_end]` 生成图片 overlay。
- Phase 5 no-key 图片链路已有测试闭环：`LocalImageTool -> execution-assets.visual_assets -> timeline -> FFmpeg overlay`。
- Runtime artifact 分层已落地：Pipeline 会写出 `plan.json`、`execution-assets.json`、`timeline.json` 和最终 `result.json`；renderer 优先消费 `PlanManifest + ExecutionAssets`，不再依赖半成品 `result.json`。
- cleanup 后的独立 review 结论：进入 Phase 5.5 前没有 must-fix blocker；剩余问题按 Phase 6 / Phase 7 / Maintenance 技术债处理。

## Phase 1: 基础架构 - 已完成

状态：已完成。

- Manifest schema。
- Scene 数据模型。
- Rule Planner。
- Scene 粒度 Manim 渲染。
- FFmpeg 合成。
- 单元测试。

参考：`changelog/phase1.md`。

## Phase 2: Shot 层 + LLM Planner - 已完成

状态：已完成。

- 引入 Shot 作为最小连续视觉单元。
- 实现 Scene + Shot 分组。
- 实现 LLM Planner 两阶段流程：Blueprint -> Chunk Mapping -> Reconcile。

参考：

- `changelog/phase2a_scene_architecture.md`
- `changelog/phase2b_llm_planner.md`
- `changelog/phase2_shot_layer.md`

## Phase 3: Tool 接口 + 基础设施 - 已完成

状态：已完成。

- Tool Protocol。
- Tool Registry。
- Tool Cache。
- 优先级调度。
- `target_duration` 契约。

参考：`changelog/phase3_tool_infrastructure.md`。

注意：早期 Adapter 层已经在 Phase 4 删除。如果以后真的需要 CLI/HTTP 工具，再重新设计，不把旧 Adapter 当成当前事实。

## Phase 4: 现有工具重构 - 已完成

状态：已完成。

- Pipeline 可以把非 `text_only` scene 分发给视觉工具。
- Tool 输出可以写回 `ShotResult.visual`。
- FFmpeg assembler 可以消费 per-shot visual。
- 删除 Adapter 死代码和 LLM Planner 旧转换逻辑。

参考：`changelog/phase4_refactor.md`。

## Phase 5: Runtime artifact 分层 + Manifest-first execution

状态：进行中。

目标：证明非文字视觉素材可以进入 pipeline，并且按 shot 出现在最终视频时间线上。

这一阶段仍属于 framework/runtime。重点不是让 agent 选得多聪明，而是让 Manifest 输入可以稳定执行，并让中间 artifact 语义清晰。

已完成或基本完成：

- [x] 已有 `PexelsImageTool`。
- [x] `PexelsImageTool` 实现 `tool_type="image"` 和 `provider_name="pexels"`。
- [x] Pexels 搜索/下载路径使用 `ToolCache`。
- [x] 有 `PEXELS_API_KEY` 时，Pipeline 会把 Pexels 注册到 `stock_image`。
- [x] Pipeline 可以分发 `stock_image` scene 到视觉工具。
- [x] Tool 输出可以填充 `ShotResult.visual`。
- [x] FFmpeg assembler 可以叠加 per-shot visual。
- [x] 已有基础 Ken Burns `zoompan` 支持。
- [x] Pexels 行为有 mock HTTP 单测。
- [x] Ken Burns filter 有单测。
- [x] `PexelsImageTool` 输出包含 `cache_key`。
- [x] 已有 `LocalImageTool`，图片链路不依赖 API key。
- [x] 已有 no-key `stock_image` 测试：`Plan -> Pipeline visual dispatch -> ShotResult.visual -> FFmpeg overlay entry`。
- [x] 文档说明 Pexels 是可选 provider，不是本地验证的前置条件。

剩余任务：

- [x] 定义 runtime artifact 分层：`plan.json` / `execution-assets.json` / `timeline.json` / `result.json`。
- [x] 新增 `ExecutionAssets` 或等价 schema，记录 audio assets 和 visual assets。
- [x] 把 TTS 产物从当前 `ResultManifest` 语义中迁到 execution-assets：音频路径、duration、provider、cache key。
- [x] 把 `LocalImageTool` / Pexels 输出写入 execution-assets 的 visual assets：shot_id、provider、path、width、height、cache key。
- [x] `plan.json` 只保留计划和目标约束，不混入实际素材产物。
- [x] renderer 消费 `PlanManifest + ExecutionAssets`，不再消费半成品 `result.json`。
- [x] assembler 消费 `PlanManifest + ExecutionAssets + timeline`。
- [x] assemble 完成后才写最终 `result.json`，记录 output MP4、used assets、warnings、artifact index。
- [x] 增加 manifest-first 输入入口，例如 `python -m md2video --plan plan.json -o output.mp4`。
- [x] 让 manifest-first 入口复用现有 TTS / Manim / FFmpeg 流程，不另写一套生成器。
- [x] 加一条不调用外部 API 的集成测试，验证 local image 进入 execution-assets，并进入最终 FFmpeg overlay 输入。
- [x] 保留全 `text_only` 行为作为回归测试路径。
- [x] 统一 manifest-first render cwd 到 artifacts，避免污染 plan 所在目录。
- [x] `timeline.json` 输出 segment_id / scene_id / shot_id / start / end。
- [x] assembler 优先使用真实 timeline 的 shot timing 做 per-shot visual overlay。
- [x] TTS audio asset 写出绝对路径，减少 `--plan` 渲染 cwd 对音频解析的影响。
- [x] 显式 local image 路径缺失时 hard fail，不继续生成缺图视频。
- [x] CLI `--voice` / `--speed` 覆盖进入 TTS 执行路径。
- [x] README 和 architecture 文档同步 runtime artifact 分层。

图片链路在新 artifact 体系里的落点：

```text
PlanManifest
scene.visual_type = "stock_image"
scene.visual_params = {"preferred_provider": "local", "path": "local_image.jpg"}

        ↓

execution-assets.json
visual_assets = [{shot_id, provider, path, width, height, cache_key}]

        ↓

timeline.json
shot / segment / marker timing

        ↓

FFmpeg overlay

        ↓

result.json
output_mp4 + used_assets + warnings
```

验收标准：

- 没有 API key 也能通过测试证明图片链路。
- `stock_image` / `LocalImageTool` 路径能通过 Manifest 输入进入 execution-assets 和 FFmpeg overlay。
- 图片事实落在 execution-assets，而不是半成品 result。
- 时间事实落在 timeline，per-shot visual overlay 优先使用 renderer 真实 shot 时间。
- 最终 `result.json` 只在 assemble 完成后生成。
- 单元测试保持通过：当前基线是 `267 passed, 5 warnings`。
- 真实 Pexels 只是可选验证，不是唯一验证方式。

## Phase 5.5: Runtime Layout Template

状态：计划中。

目标：把“用什么视觉素材”和“画面怎么摆”分开。

这一阶段仍属于 framework/runtime，不属于 harness。Layout Template 是稳定排版约束，agent 或 planner 只能选择模板和参数，不能自由决定像素坐标。

计划任务：

- [ ] 在 Manifest 中新增一等布局字段，暂定 `layout_type` + `layout_params`。
- [ ] 保留 `visual_type` 表达素材/工具选择：`text_only`、`stock_image`、`local_image`、`manim`、`stock_video` 等。
- [ ] 用 `layout_type` 表达画面摆法：全屏图+底部字幕、上图下文、左图右文、纯文字标题页等。
- [ ] 定义 `LayoutTemplate`。
- [ ] 定义 `LayoutRegistry`。
- [ ] 先实现 2-3 个稳定模板：
  - `center_title_body`
  - `full_bleed_image_caption_bottom`
  - `image_top_text_bottom` 或 `image_left_text_right`
- [ ] layout 参数必须是有限选项，并且能做 schema 校验。
- [ ] 增加 safe area、文字边界、字幕/图片不重叠测试。

验收标准：

- Agent 或 Planner 只能选择模板和参数。
- 不允许自由决定像素坐标。
- 不生成完整视频也能测试 layout 计算和约束。

## Phase 6: Renderer Closure

状态：计划中。

目标：让渲染器消费和其他环节一致的 Shot + Layout + ExecutionAssets 模型。

当前不匹配的地方：

- `ManimRenderTool.execute()` 仍然是 stub。
- Pipeline 仍然用 subprocess 特判 Manim。
- `manim_renderer.py` 仍然主要按 segment 循环渲染。
- 仍有 `self.wait(2)` 这类硬编码等待。
- `target_duration` 已经算出来，但 Manim 还没有真正消费它。
- renderer 已优先消费 `plan.json` / `execution-assets.json`，但 Manim 仍由 Pipeline subprocess 特判调用，还没有成为标准 Tool backend。
- 预生成音频仍按 `result_manifest.segments` 顺序消费，而不是按 `segment_id` 绑定；当前 RulePlanner 主路径顺序一致，但 manifest-first 自定义顺序可能把错误音频配到文本上。

计划任务：

- [ ] 实现 `ManimRenderTool.execute()`。
- [ ] Tool 路径可用后，移除 Pipeline 对 Manim subprocess 的特殊分支。
- [ ] Renderer 显式接收 `PlanManifest + ExecutionAssets + layout`。
- [ ] 文件 artifact 只是输出记录，不是 renderer 的隐藏输入状态。
- [ ] 按 Shot 渲染，而不是松散的 segment 循环。
- [ ] 传递并消费 `target_duration`。
- [ ] 用时长感知渲染替代硬编码 wait。
- [ ] 支持无音频或静音 demo。
- [ ] 让 Manim 消费 `LayoutTemplate`。
- [ ] 让 FFmpeg 图片/视频布局也消费同一套 layout 契约。
- [ ] 把可复用 Manim 模板重新定义为 layout/render backend，而不是零散视觉效果。
- [ ] 把 renderer 音频播放从“按列表顺序消费”改为“按 `segment_id` 查找 audio asset”，避免自定义 manifest 顺序变化时配错音频。

验收标准：

- text-only 视频仍正常。
- Shot 时长跟随 TTS 时间。
- Manim 和 FFmpeg 对 layout 的理解一致。
- renderer 不依赖旧的 stale manifest/result 文件。

## Phase 7: Runtime Inspectability

状态：计划中。

目标：让 runtime 的中间结果对人和未来 harness 可检查。

这还不是完整 preview/review harness，只是输出可读、可追踪、可诊断的中间结果。

计划任务：

- [ ] 输出 artifact index，记录本次生成的 plan、execution-assets、timeline、result、音频、图片、视频路径。
- [ ] 输出一份紧凑、可读的静态查看页面，例如 `plan.html` 或 `manifest_viewer.html`。
- [ ] 展示 plan：segments、scenes、shots、visual intent、layout intent。
- [ ] 展示 execution-assets：audio assets、visual assets、provider、cache key、尺寸、路径。
- [ ] 展示 timeline：renderer 实际字幕、marker、shot 或 segment 时间。
- [ ] 展示 result：最终 MP4、used assets、warnings、artifact index。
- [ ] 展示 warning：provider 缺失、降级到文字、时长差异、layout 风险等。

验收标准：

- 人不用读原始 JSON 也能看懂将要渲染什么、实际用了哪些素材、最终产出了什么。
- 这一阶段不要求完整编辑、审批、局部重跑 UI。
- 输出结果可以被未来 harness 直接读取。

已知技术债：

- [ ] 定义 run-dir 生命周期策略：`manim_render_*` 临时子目录可以保留用于 debug，但需要被 artifact index 索引或按策略清理。
- [ ] final `result.json` 应索引 base render MP4、assembled MP4、plan、execution-assets、timeline 和关键临时产物。
- [ ] 新 run 开始时显式标记 run id/status，或清理/失效旧 `result.json`、`timeline.json`，避免失败路径留下“新 plan/assets + 旧 result/timeline”的混合 artifacts。

## Future: Harness / Agent Workflow Layer

这些属于未来 harness/workflow，不应该混进当前 runtime 交付。

- `md2video` Codex/Raft skill。
- 视频任务上下文打包。
- Agent 生成或编辑 `PlanManifest`。
- Agent 选图、写 query、提出 layout 建议。
- Preview/review UI。
- 人工替换图片、调整 layout、确认或驳回 shot。
- 局部 shot 重生成。
- 局部重跑。
- eval 检查。
- 人工验收流程。

## Idea Pool

这些先保留为想法，等 runtime 稳定后再判断优先级。

- Remotion backend。
- AI image provider 插件。
- AI video provider adapter：Runway / Kling / Sora 等。
- AI 作曲或环境音效生成。
- 世界模型驱动视频。

## Maintenance

Docs mismatch / consistency：

- [x] README 已补充直接依赖 `requests`。
- [x] README / config 已收敛为 OpenAI-compatible LLM planner，不再把 Anthropic 写成当前支持项。
- [x] README / TODO 测试基线已更新到 `267 passed, 5 warnings`。
- [x] TODO 已删除“是否需要 owner 授权真实短视频 demo”的 stale 项；demo 不作为当前 commit 的交付内容。
- [ ] 定期核对 README、TODO、`docs/architecture.md` 对 runtime artifact 分层的描述，避免 `result.json` 再被写成中间执行状态。

Test / cleanup：

- [ ] 决定 README 是否继续写固定测试数量，还是只写最新验证命令。
- [ ] 调查当前 5 个 pytest warnings，来源主要是 mock async TTS 调用。
- [ ] 补测试：音频按 `segment_id` 绑定，不依赖 segment 列表顺序。
- [ ] 补测试：失败 run 不会让旧 `result.json` / `timeline.json` 被误认为当前 run 产物。
- [ ] 补测试：非 0 起点 image shot 的 FFmpeg overlay / Ken Burns timing 正确。
