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
= 意图和目标约束：segments / scenes / shots / visual_type / visual_params / layout（不含时间）

execution-assets.json
= 素材事实：TTS 音频路径、音频时长、图片路径、图片尺寸、provider、cache key

timeline.json
= 时间事实：renderer 实际输出；shots/text 使用 `start/end`，marker cue 使用 `time`

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

- Phase 1-6 已完成：渲染契约 + layout consumption 落地，像素级 smoke 验证通过。
- 设计共识定稿（2026-09-05）：四本账、四道闸门、双 track 路线。设计定义见 `docs/architecture.md`（「总体模型」「覆盖地图」）。
- Track A 首批已落地（2026-09-06）：A1 时间不变量闸门 + A2.5 渲染后端去硬编码 + A2/B1 Style Pack（`ink_night`，像素逐帧不变验收）+ A3 Plan Schema v2（plan 不含时间，一次切换完成）。
- 最新验证：2026-09-06 运行 `python -m pytest -q`，结果是 `484 passed, 1 skipped`；skip 的是 `MD2VIDEO_RENDER_SMOKE=1` 才运行的真实渲染像素 smoke（`tests/test_render_smoke.py`）。
- 已有旧的 Markdown -> MP4 流程：`python -m md2video example/example.md -o artifacts/output.mp4`。
- 已知问题：LLM planner API key 401（配置问题，Rule planner fallback 正常）。
- 后续施工按 Track A / Track B 推进；原 Phase 7 计划并入 A4。

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

状态：已完成。

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

完成任务：

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
- 单元测试保持通过：当前基线是 `352 passed, 3 warnings`。
- 真实 Pexels 只是可选验证，不是唯一验证方式。

## Phase 5.5: Runtime Layout Template

状态：已完成。

目标：把“用什么视觉素材”和“画面怎么摆”分开。

这一阶段仍属于 framework/runtime，不属于 harness。Layout Template 是稳定排版约束，agent 或 planner 只能选择模板和参数，不能自由决定像素坐标。

计划任务：

- [x] 在 Manifest 中新增一等布局字段，暂定 `layout_type` + `layout_params`。
- [x] 保留 `visual_type` 表达素材/工具选择：`text_only`、`stock_image`（含 local provider）、`stock_video` 等；`manim` 只作为 `render/manim` backend。
- [x] 用 `layout_type` 表达画面摆法：全屏图+底部字幕、上图下文、纯文字标题页等。
- [x] 定义 `LayoutTemplate`。
- [x] 定义 `LayoutRegistry`。
- [x] 先实现 2-3 个稳定模板：
  - `center_title_body`
  - `full_bleed_image_caption_bottom`
  - `image_top_text_bottom`
- [x] layout 参数必须是有限选项，并且能做 schema 校验。
- [x] 增加 safe area、文字边界、字幕/图片不重叠测试。

验收标准：

- Agent 或 Planner 只能选择模板和参数。
- 不允许自由决定像素坐标。
- 不生成完整视频也能测试 layout 计算和约束。

交付边界：

- 本阶段完成 Manifest/layout-engine 契约和 runtime 校验。
- Manim / FFmpeg 真正消费 `LayoutTemplate` 仍归 Phase 6。

Phase 5.5 review guardrails：

- [x] 文档不得把未实现模板写成已完成范围；当前内置模板只有 `center_title_body`、`full_bleed_image_caption_bottom`、`image_top_text_bottom`。
- [x] Layout 参数不能接受“看似有效但当前不生效”的字段；caption 样式类参数留到 Phase 6 renderer 真正消费时再引入。
- [x] `LayoutRegistry` 重复注册同一个 template id 时必须 fail fast，避免未来扩展时静默覆盖。
- [x] Phase 6 接入 renderer/assembler 后补像素级 smoke，验证视频画面确实按 layout 摆放（`tests/test_render_smoke.py`，`MD2VIDEO_RENDER_SMOKE=1` 触发真实渲染 + 合成 + 取帧断言）。

## Phase 6: Renderer Closure

状态：已完成。renderer contract cleanup 与 layout consumption 均已落地并通过像素级 smoke。

目标：完成新的 renderer contract，让渲染器消费和其他环节一致的 Segment + Shot + Layout + ExecutionAssets 模型，并把 renderer 输出的 timeline 变成 assembler 可直接信任的时间事实。

Phase 6 的收敛方向：

```text
plan.segments
= 内容字典；Segment 是内容原子，目标语义上持有 duration budget

scene.shots[].segment_ids
= 执行顺序；Shot 是连续视觉执行单元

scene.shots[].cues
= marker / media / visual event metadata；不显示、不朗读、不消费 duration

renderer scheduling helpers
= 把 segment / marker / layout / target budget lower 成 render units 和 cues

timeline.json
= renderer 运行后的时间事实；shots 是主时间轴，text/markers 是 shot 内 cue
```

Breaking contract：Phase 6 不再保留旧 renderer contract。`target_duration` 迁移到 Segment；`ShotPlan.target_duration` 删除；marker 不再作为可渲染 segment，而是在 planning/render scheduling 阶段 lower 成 shot cue/metadata；有 scenes/shots 的 plan 必须完整覆盖可渲染 segments，不再保留 flat fallback。

当前状态：

- `layout/mapping.py` 是 Manim 与 FFmpeg 共用的坐标换算层：normalized region -> 单位空间（渲染器）/ 像素空间（合成器），两边对同一模板的理解来自同一组函数。
- Renderer 按 shot 用 `shot_layout_context` 解析 region：正文/字幕堆叠落在 body/text/caption region，标题卡片落在 title region，文本按 region 宽度约束缩放；没有 image region 的布局保留 marker 图片出现时的 legacy 文本让位。
- FFmpeg per-shot visual 用 scene layout 的 `image` region 摆放：Ken Burns cover 整个 region，静态 overlay contain 进 region；`timeline.json` 的 shots 条目现在记录 `layout_type`。
- Markdown marker 图片 overlay 保留 legacy 定位：marker 时间区间可跨 shot，不强行套单个 scene 模板。
- 渲染分辨率修复：ManimRenderTool 不再传 Manim 质量旗标（`-ql` 会把 manim.cfg 声明的 480x854 竖屏覆盖成 854x480 横屏），分辨率/帧率由 manim.cfg 决定。

已完成的过渡工作：

- [x] renderer helper 已验证 shot 顺序、unknown segment、title skip、silent path、layout 信息携带。
- [x] render tool 已能清理 stale timeline，并校验 timeline 覆盖当前 plan。
- [x] renderer 音频播放已从“按列表顺序消费”改为“按 `segment_id` 查找 audio asset”。
- [x] 上述 helper/test 已按新 schema / shot cue marker contract 调整。

计划任务：

- [x] 实现 `ManimRenderTool.execute()`。
- [x] Tool 路径可用后，移除 Pipeline 对 Manim subprocess 的特殊分支。
- [x] Renderer 显式接收 `PlanManifest + ExecutionAssets`。
- [ ] Renderer 消费 `layout_type` / `layout_params` / `LayoutTemplate`。
- [x] 文件 artifact 只是输出记录，不是 renderer 的隐藏输入状态。
- [x] RenderTool 在渲染前清理旧 `timeline.json`，并在渲染后校验本次生成的 timeline。
- [x] RenderTool 会校验 timeline 覆盖当前 plan 的 shot 和 segment。
- [x] Pipeline 会在 assemble 前校验 render backend 输出字段和文件存在性。
- [x] Renderer manifest/env loader 已从 Manim 场景模块中抽出为轻量 helper，避免纯输入测试依赖 Manim。
- [x] Renderer 输入契约已有纯 helper 测试，覆盖标题正文遍历、未知 segment 引用、音频 asset 绑定和 `visual_type` 边界。
- [x] Timeline 写入已改为按 handle 关闭，并有重复文本/同文本 header-content 的回归测试。
- [x] 补 renderer helper contract 测试：shot 顺序是主遍历顺序、unknown segment fail fast、title 不进正文、marker 进入 timeline 路径、layout 决策进入 render unit。
- [x] 补 duration helper 测试：silent content/header 可从 result duration 或 shot target 推导时长，voiceover 仍以音频/voiceover 为主。
- [x] 支持无音频或静音 demo 的输入校验：没有 audio assets 且 segment 没有 `audio_request` 时不报错；silent path 不初始化 `CachedVoiceService`。
- [x] Schema cleanup：新增 `SegmentPlan.target_duration`，删除 `ShotPlan.target_duration`。
- [x] Schema cleanup：给 `ShotPlan` 增加 cue/metadata 字段，用于 marker / media / visual event。
- [x] Schema cleanup：删除或拒绝旧 marker-as-rendered-segment 语义。
- [x] Parser/Planner lowering：Markdown marker 仍可被识别，但最终 Plan 里 marker 应进入 shot cue/metadata。
- [x] Parser/Planner validation：planner 必须保证所有可渲染 segment 都被某个 shot 引用。
- [x] Runtime validation：有 scenes/shots 时 orphan segment fail fast；删除无 scenes 的 flat fallback。
- [x] Renderer scheduling helper：生成 shot render unit，而不是 segment render unit。
- [x] Shot render unit 必须包含 scene contract、layout contract、ordered segments、segment durations、marker cues。
- [x] Duration：按 segment 计算预算和实际等待；shot duration 是内部 segment/cue 聚合结果。
- [x] Duration：voiceover segment 以音频/voiceover 为主；silent segment 使用 `SegmentPlan.target_duration` 或 layout/render template 默认。
- [x] Renderer timeline：renderer 显式 open/close shot，直接写出 `timeline.json.shots[].start/end`。
- [x] Renderer timeline：`timeline.text` 只表示可见文本 cue；`timeline.markers` 只表示事件 cue，不参与反推 shot。
- [x] 让 Manim 消费 `LayoutTemplate`：`shot_layout_context` / `title_layout_positions`，region 内摆放 + 宽度约束。
- [x] 让 FFmpeg 图片布局消费同一套 layout 契约：`attach_image_layout_regions` + region overlay（cover/contain）。
- [x] 坐标换算收敛到共享 `layout/mapping.py`，Manim 与 FFmpeg 不再各自解释模板。

验收标准：

- text-only 视频仍正常。
- 有声 segment 的朗读时长跟随音频/voiceover，silent segment 也有明确时长。
- Shot timeline 是 renderer 显式输出的主时间轴。
- marker 是 shot cue/metadata，不作为正文显示或朗读。
- Manim 和 FFmpeg 对 layout 的理解一致。
- renderer 不依赖旧的 stale manifest/result 文件。

## Track A: Infrastructure

目标：完善裁判、账本、闸门与机制。设计定义见 `docs/architecture.md`（总体模型 / 覆盖地图）。

### A1 契约收紧

目标：把时间与配置的事实约束补成闸门。纯收紧，无 breaking。

- [x] 新增 `timeline/invariants.py` 纯函数检查器：shots 覆盖全部 plan shots、按序、两两不重叠、无负时长；text cue 落在所属 shot 区间；marker 落在所属 shot 边界；朗读段时长与音频事实差值告警。
- [x] 接入渲染后闸门（manim_tool 现有校验逻辑搬入，行为保持）。
- [x] 清理 `stock_video` 幽灵配置（`DEFAULT_TOOL_PRIORITY` 中已声明、无工具注册）。
- [x] 补测试：非 0 起点 image shot 的 FFmpeg overlay / Ken Burns timing 正确。

验收：构造重叠/乱序/缺 cue 的 timeline 必须被拒且报错可定位；example 端到端不受影响。✅（2026-09-06：闸门拒绝测试全绿；example 端到端两次运行 framemd5 逐帧全等）

### A2 Style Pack 机制

目标：风格声明化——token 声明 + 每引擎一个 Realizer。与 B1 同一里程碑，互相验收。

- [x] `md2video/style/`：ThemeTokens schema（palette / typography 归一化字号 / motion 意图级 + 静默段节奏 / motif 槽位）。
- [x] pack 加载与 token 校验（v0 代码内置注册，外部文件加载留接口）。
- [x] ManimRealizer：token → 引擎参数的唯一换算点；动效意图映射；motif kind 注册表（orbit_dots 圆点代码从渲染器搬家至此）。
- [x] 渲染器切换为消费 token；风格常量退役（DEFAULT_FONT 等）。
- [x] 与 B1（reference pack）联合验收。

验收：`MD2VIDEO_RENDER_SMOKE=1` 像素逐帧不变（抽取无损的硬标准）。✅（2026-09-06：smoke 计划前后渲染 framemd5 逐帧全等 + timeline 字节一致；example 端到端 framemd5 逐帧全等）

### A2.5 渲染后端去硬编码

- [x] render provider 从 plan/配置读取，替换 pipeline 中的 `"manim"` 硬编码与 provider 校验。

验收：注册新后端后可整条切换，不改管线代码。✅（2026-09-06：`ToolConfig.render_backend` + `MD2VIDEO_RENDER_BACKEND`；切换测试全绿）

### A3 Plan Schema v2 + 时间合同

目标：plan 不含时间。**Breaking：是**（唯一一次 schema 破坏性迁移）。

- [x] 删除 `SegmentPlan.target_duration`；段时长裁决统一为：音频事实 > hold cue > pack 节奏（v1 = 音频事实 > pack 节奏，hold cue 留概念位）。
- [x] 删除 `pipeline._fill_target_durations` 回写。
- [x] SegmentPlan 的 visual/layout 副本字段收拢到 scene 级（去 denormalize，与去时间同一次迁移）。
- [x] Tool Protocol + VisualAsset 增加 duration 合同（视频素材 probe 上报）。
- [x] 时长估算器纯函数（音频事实 + pack 节奏 + 转场开销常数）——只服务容错决策与展示，永不用于组合。
- [x] schema 迁移 validator + 一次切换；受影响测试同步改写。

验收：plan.json 无时长字段；example 端到端输出不变；估算器有单测。✅（2026-09-06：example 端到端 framemd5 逐帧全等；plan.json 无时长字段；`timeline/estimate.py` 有单测）

### A4 Runtime Inspectability（原 Phase 7 全部内容）

目标：让 runtime 的中间结果对人、对未来 harness、对 LLM 反馈回路可检查。

- [x] 输出 artifact index，记录本次生成的 plan、execution-assets、timeline、result、音频、图片、视频路径。
- [x] 输出紧凑可读的静态查看页面（`manifest_viewer.html`）。
- [x] 展示 plan：segments（类型/文本/角色）、shots with cues、scenes with visual/layout/theme intent。
- [x] 展示 execution-assets：audio/visual assets、provider、cache key、尺寸、duration、路径。
- [x] 展示 timeline：shot 主时间轴、text cue、marker cue、实际 duration。
- [x] 展示 result：最终 MP4、used assets、warnings、artifact index。
- [x] 展示 warnings：provider 缺失、降级、时长差异、style 缺失/降级。
- [x] 展示预计 vs 实际时长（消费 A3 估算器 + timeline）。
- [x] 吸收技术债：旧 `result.json` 失效问题——每次 run 独立目录 `artifacts/runs/<run_id>/`（新建+命名区分，永不覆盖/删除），`FinalResultManifest` 增加 `run_id` 与 `status`（completed/failed），失败 run 在自己目录写 failed result，混合 artifacts 在结构上不可能。
- [x] 吸收技术债：`manim_render_*` run-dir 生命周期策略——渲染目录落进本次 run 目录并登记 artifact_index；按用户拍板不做任何自动清理（产物只增不删）。

验收：人不用读原始 JSON 能看懂一次运行；输出可被未来 harness 直接读取；不要求编辑/审批 UI。✅（2026-09-06：viewer 结构化断言 + 黄金快照测试；example 端到端 framemd5 逐帧全等）

### A5 Layout 提案机制

目标：layout 从"模板选择"升级为"约束机制"。

- [ ] `ScenePlan.layout_regions` 直接提案入口（与模板走同一套属性校验）。
- [ ] 结构化 LayoutIssue：code + region + 数值差 + 修改建议，一次报全部问题。
- [ ] 约束注册表（设计包可注册追加约束）。
- [ ] 子构图 region 化：section header 左列堆叠改由模板子 region 表达。

验收：非法提案得到可执行的结构化报错；现有模板路径行为不变。

### A6 混合引擎（按 scene）

目标：不同 scene 用不同渲染引擎；Remotion 作为第一个真实第二后端。

- [ ] scene 级 `render_backend` 字段；要求的后端未注册时开渲前 fail fast。
- [ ] 按 scene 分组分发：plan 切片 → 各后端 → N 段视频 + N 份局部 timeline。
- [ ] 视频拼接（concat，编码参数一致）+ timeline 前缀和偏移合并 → 重过全局闸门。
- [ ] 组边界状态策略：引擎切换即场景切换，渲染器内部跨 shot 状态（字幕堆叠/母题）清零。
- [ ] Remotion 后端：同一渲染契约 + 自带 Realizer + 能力词汇声明（动效意图、母题 kind）。

验收：混合 manim/remotion 的 plan 出一条成片；Remotion 通过全部闸门。

### A7 内容槽位（按需阀门）

识别归 infra（parser/schema/降级规则），表现归 pack。只在 B 系列包需要时激活。

- [ ] parser 识别列表/加粗/引用 → 新 segment 类型；不支持的 pack 强制降级 + warning。
- [ ] 表现语义（列表逐条浮现、金句、引用样式）由 pack 提供。

验收：带列表/引用的 markdown 出片；不支持的 pack 干净降级。

## Track B: 自研设计包

目标：框架自带"开箱能看"的参考设计，并验证社区包路径。包 = 纯数据宣言（palette/typography/motion/motif 槽位），不含引擎代码；引擎与包正交，能力按名字引用。

### B1 Reference Pack（与 A2 同一里程碑）

- [x] 现有 house style（黑底白字仿宋 + 圆点母题 + 现节奏常量）抽取为 `ink_night` pack。
- [x] 与 A2 联合验收：像素逐帧不变。✅（2026-09-06）

### B2 知识口播 Pack

- [ ] 节奏、字号梯度、母题、内容表现语义（列表逐条浮现、金句、引用）。
- [ ] 需要 A7 槽位时按需触发。

验收：一篇带列表/引用的知识 markdown 出"至少能看、不划走"的片。

### B3（远期）第二套风格

- [ ] 外部结构落地第二套 pack，验证"社区包与内置包零特权差别"。

## 里程碑与依赖

依赖链：**A1、A2.5 随时可做；A2 + B1 绑定落地 → A3（静默节奏来源 = pack motion token）→ A4（viewer，B2 调参受益）→ B2（按需触发 A7）→ A5 → A6**。breaking 迁移只有 A3 一次。

## Future: Harness / Agent Workflow Layer

这些属于未来 harness/workflow，不应该混进当前 runtime 交付。

前置条件：A4 viewer（LLM 反馈回路）、A5 提案机制（结构化报错）、LLM planner API 配置修复（当前 401）。

- `md2video` Codex/Raft skill。
- 视频任务上下文打包。
- Agent 生成或编辑 `PlanManifest`：内容、shot grouping、scene layout/theme 选择、cue 与显式停顿（hold cue）。
- Agent 选图、写 query、提出 layout 提案，但不能写自由像素坐标，也不能绕过约束校验。
- Preview/review UI。
- 人工替换图片、调整 layout、确认或驳回 shot。
- 局部 shot 重生成。
- 局部重跑。
- eval 检查。
- 人工验收流程。

## Idea Pool

这些先保留为想法，等 runtime 稳定后再判断优先级。

- Remotion backend：必须实现同一 renderer contract，并输出同结构 timeline（Track A6 的验收工程）。
- AI image provider 插件：只能产出 execution-assets，不直接改 timeline。
- AI video provider adapter：Runway / Kling / Sora 等，只能作为 visual assets/provider 接入。
- AI 作曲或环境音效生成：放在 runtime contract 稳定之后。
- 世界模型驱动视频。

## Maintenance

Ops / config：

- [ ] 修复 LLM planner API 配置（`.env` key 当前 401；Skill / LLM planner 生效前提）。

Docs mismatch / consistency：

- [x] README 已补充直接依赖 `requests`。
- [x] README / config 已收敛为 OpenAI-compatible LLM planner，不再把 Anthropic 写成当前支持项。
- [x] TODO 测试基线已更新到 `352 passed, 3 warnings`。
- [x] TODO 已删除“是否需要 owner 授权真实短视频 demo”的 stale 项；demo 不作为当前 commit 的交付内容。
- [ ] 定期核对 README、TODO、`docs/architecture.md` 对 runtime artifact 分层的描述，避免 `result.json` 再被写成中间执行状态。
- [ ] 定期核对 README、TODO、`docs/architecture.md` 不再把 Segment 写成“最小时间单元”。
- [ ] 定期核对文档不再把 `ShotPlan.target_duration` 写成长期设计。
- [ ] 定期核对文档不再把 marker 写成正文渲染路径。
- [ ] 定期核对文档不再把 `timeline.shots` 写成可由 text/marker 反推。
- [x] 定期核对文档术语与实现一致：四本账、pack、Realizer、约束机制；target_duration 移除后清理全部文档残留。

Test / cleanup：

- [x] README 不再写固定测试数量；测试基线只保留在 TODO 的最新验证记录中。
- [x] 补像素级 smoke：`MD2VIDEO_RENDER_SMOKE=1` 触发真实 Manim 渲染 + FFmpeg 合成，断言文字/图片按 layout region 落位（`tests/test_render_smoke.py`）。
- [x] 修复渲染分辨率 bug：`-ql` 质量旗标覆盖 manim.cfg 的竖屏声明导致横屏输出。
- [ ] 调查当前 pytest warnings，来源主要是 mock async TTS 调用和部分第三方 deprecation。
- [x] 补测试：音频按 `segment_id` 绑定，不依赖 segment 列表顺序。
- [x] 补测试：render 成功但未生成新 `timeline.json` 时 hard fail，不复用旧 timeline。
- [x] 删除或重写旧 flat fallback 测试。
- [x] 删除或重写依赖 `ShotPlan.target_duration` 的测试。
- [x] 重写 marker-as-segment 的 renderer 测试为 marker-as-shot-cue。
- [x] 补测试：失败 run 不会让旧 `result.json` 被误认为当前 run 产物（并入 A4，run 目录制落地）。
- [x] 补测试：非 0 起点 image shot 的 FFmpeg overlay / Ken Burns timing 正确（并入 A1）。
