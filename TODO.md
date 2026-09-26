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
- Track A 第二批已落地（2026-09-07）：A4 Runtime Inspectability（run 目录制 + `manifest_viewer.html`）+ A5 Layout 提案机制（`layout_regions` + 约束注册表 + 结构化 LayoutIssue + 子构图 region 化）+ 外部皮肤包文件加载（`MD2VIDEO_STYLE_PACK_FILE`）+ A6 前半（按 scene 多后端分发与合成基础设施）。
- Track A 第三批已落地（2026-09-07 晚）：A9 OTIO 导出（`timeline.otio` 交付形态）+ A6 后半（Remotion 真实第二后端：Python 调度器 + Node composition，能力词汇声明与降级，混合 manim/remotion 出片，双跑 framemd5 逐帧一致）。
- Track A 第三批补验（2026-09-08）：CLI 全链路真跑（rule planner + edge-tts 配音 + Remotion 渲染 + FFmpeg 装配）暴露并修复三个 mock 盖不住的集成 bug——①`remotion_tool` 子进程 cwd 切到 backend_dir 后相对路径错位（props 找不到/视频写错目录，先 `resolve()` 再传 CLI，补相对路径回归测试）；②`ffmpeg_assembler.ffprobe_resolution` 对 Remotion 容器多出的尾部空字段（`480x854x`）做 `int('')` 炸裂（只取前两段）；③调度器 before/after 锚点 cue（真实 markdown 的 `[image_start]`/`[music_*]` 全走这条路）挂上时间后从未 append 进 `markers_out`，时间闸门直接拒绝且图片/BGM 条目为空（锚前=段起点、锚后=段终点落盘；锚点段不在本 shot 时收敛到本 shot 末端）。修正早前错误结论：图片/BGM 不需要进 Remotion payload——正文由组件按 region 画，图片/Ken Burns 与 BGM 由后端无关的装配层按 timeline marker 叠加；marker 修复后带图+BGM 的 `example.md` 走 Remotion 完整出片（66.6s，抽帧验证 `image_top_text_bottom` 版式成立、窗口外无图）。
- 最新验证：2026-09-14 运行 `python -m pytest -q`，结果是 `657 passed, 6 skipped, 2 warnings`；skip 的是 env-gated 真渲染用例（`MD2VIDEO_RENDER_SMOKE=1` 像素 smoke、multi_backend 真渲染验收、remotion 单后端与混合后端真渲染），warnings 是上游第三方 deprecation（cloup/pydub，见 Maintenance）。
- 近期主线已完成（2026-09-12）：~~「组件注册 + 口播 skill」~~ ✅——场景风格由注册组件承载（plan 引用 `id@version`），知识口播 craft 由 skill 承载（`skills/voiceover/SKILL.md`，agent 读结构化 markdown、经 `--plan` 直产 plan）。
- 已有旧的 Markdown -> MP4 流程：`python -m md2video example/example.md -o artifacts/output.mp4`；中间产物按 run 落在 `artifacts/runs/<run_id>/`（永不覆盖），附 `manifest_viewer.html` 检查页。
- 已知问题：LLM planner API key 401（配置问题，Rule planner fallback 正常）。
- 后续施工：~~LLM planner 前缀修复~~ ✅、~~A8 组件管线~~ ✅、~~口播 skill v1~~ ✅（首片 71s，见 B2）、~~A8.1 场景画布~~ ✅（2026-09-13，`math_canvas@1.0.0` 入库 + showcase 首片 65.7s）。A7 维持挂起。~~知识区格式冲刺~~ ✅（P0 代码生图/烧录字幕/BGM+skill 套路/验收片 + P1 math_canvas 迭代至 1.5.0、step_list 1.0.2、知识区对标片拆解，2026-09-14 收官）。**目标定调（2026-09-14）：开源发布、向别人展示框架的潜力，demo 物料优先**；agent 视觉读片（coding agent 抽帧）完成 `trig_circle_kf` 全片体检：4 个 bug 级问题 + 2 个短板（字幕/组件文字重复、组件水印泄漏、标题卡版式+副标题溢出、CJK 折行孤字/词中断行、label 避让、静帧）——结论：**demo 不达标是具体策略/实现问题，不是路线问题**。**当前批次：demo 整改 + 开源展示（见「下一批」节）——P0 demo 整改（去重/水印/标题卡/折行）→ P1 微动效+label → P2 MCP/README/GIF/样例片矩阵。**

## Phase 1-4: 基础架构 → 现有工具重构 - 已完成

- Phase 1：Manifest schema、Scene 数据模型、Rule Planner、Scene 粒度 Manim 渲染、FFmpeg 合成、单元测试（`changelog/phase1.md`、`phase1.1_unit_tests.md`、`phase1.2_media_embedding_fixes.md`）。
- Phase 2：Shot 层（Segment→Shot→Scene）+ LLM Planner 两阶段（Blueprint → Chunk Mapping → Reconcile）（`changelog/phase2a_scene_architecture.md`、`phase2b_llm_planner.md`、`phase2_shot_layer.md`）。
- Phase 3：Tool Protocol / Registry / Cache / 优先级调度 / `target_duration` 契约（`changelog/phase3_tool_infrastructure.md`）。早期 Adapter 层已在 Phase 4 删除；将来真需要 CLI/HTTP 工具时重新设计。
- Phase 4：pipeline 分发非 `text_only` scene 到视觉工具、Tool 输出写回 `ShotResult.visual`、assembler 叠加 per-shot visual、删除 Adapter 死代码与 LLM Planner 旧转换逻辑（`changelog/phase4_refactor.md`）。

（原逐项任务清单见 git history，2026-09-12 压缩，行为零变化。）

## Phase 5: Runtime artifact 分层 + Manifest-first execution - 已完成

建立的契约（细节见 `docs/architecture.md`「Runtime Artifacts」）：

- 四类账本各管一摊：`plan.json` 只放意图与目标约束；`execution-assets.json` 放素材事实（音频/图片路径、duration、尺寸、provider、cache key）；`timeline.json` 是 renderer 输出的时间事实；`result.json` 只在 assemble 完成后写出（output MP4、used assets、warnings、artifact index）。
- manifest-first 入口 `python -m md2video --plan plan.json -o output.mp4`：复用同一 TTS / 渲染 / 合成流程，不另写生成器；manifest-first 渲染 cwd 统一到 artifacts。
- 图片链路：`stock_image`（local 免 key / Pexels 可选 key）→ visual assets（显式本地图片缺失 hard fail）→ FFmpeg per-shot overlay 优先用真实 timeline 的 shot timing。
- TTS 音频按 `segment_id` 绑定、绝对路径落盘；CLI `--voice` / `--speed` 进入 TTS 执行路径。

验收：无 API key 也有完整图片链路集成测试；text-only 行为保留为回归路径。逐项任务勾稽与验收记录见 git history（2026-09-12 压缩，行为零变化）。

## Phase 5.5: Runtime Layout Template - 已完成

- 「用什么视觉素材」（`visual_type`）与「画面怎么摆」（`layout_type` + `layout_params`）拆成两个决定，布局字段是 Manifest 一等公民；`manim` 只是 `render/manim` backend，不是 visual provider。
- 内置模板 3 个：`center_title_body`、`full_bleed_image_caption_bottom`、`image_top_text_bottom`；参数为有限选项、模板自己的 Pydantic schema 校验。
- Agent/Planner 只能选模板和参数，不允许自由像素坐标；不生成完整视频也能测试 layout 计算与约束。
- Guardrails：registry 重复注册同一 template id 必须 fail fast；layout 参数不接受「看似有效但当前不生效」的字段（caption 样式参数推迟到 renderer 真正消费时引入，已在 Phase 6 落地）。

交付边界：本阶段完成 Manifest/layout-engine 契约与 runtime 校验；Manim / FFmpeg 真正消费归 Phase 6（像素 smoke 验证已补）。逐项任务勾稽见 git history（2026-09-12 压缩，行为零变化）。

## Phase 6: Renderer Closure - 已完成

renderer contract cleanup 与 layout consumption 均已落地并通过像素级 smoke。收敛后的契约（细节见 `docs/architecture.md`「Runtime Contract」）：

- `plan.segments` 是内容字典；`scene.shots[].segment_ids` 是执行顺序；Shot 是最小连续视觉执行单元，marker/media/visual event 以 cue 挂在 shot 上——不显示、不朗读、不消费 duration，不再有 marker-as-segment 语义。
- Renderer 显式消费 `PlanManifest + ExecutionAssets`，按 shot 生成 render unit（scene contract + layout contract + ordered segments + durations + cues），显式 open/close shot 写出 `timeline.json`：`shots[].start/end` 是主时间轴，`text` 只是可见文本 cue，`markers` 只是事件 cue，不参与反推 shot。
- 时长裁决：有声段跟随音频事实（音频按 `segment_id` 绑定播放），静默段有明确默认时长来源；plan 不含时间（`ShotPlan.target_duration` 在本阶段删除、`SegmentPlan.target_duration` 随 A3 v2 移除）。
- 有 scenes/shots 的 plan 必须完整覆盖可渲染 segments，orphan fail fast，无 flat fallback；渲染前清理 stale timeline、渲染后校验覆盖当前 plan；Pipeline 在 assemble 前校验 render backend 输出字段与文件存在性。
- Manim 与 FFmpeg 经共享坐标层 `layout/mapping.py` 消费同一套 layout：正文/字幕落 body/text/caption region、标题卡落 title region、文本按 region 宽度缩放；per-shot visual 按 scene layout 的 `image` region 摆放（Ken Burns cover / 静态 contain）；marker 图片 overlay 保留 legacy 定位（时间区间可跨 shot，不强行套单个 scene 模板）。
- 分辨率由 `manim.cfg` 声明（480x854 @30fps 竖屏），渲染 backend 不传质量旗标（`-ql` 曾把竖屏覆盖成横屏，已修）。

逐项任务勾稽、breaking contract 细节与验收记录见 git history（2026-09-12 压缩，行为零变化）。

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
- [x] pack 加载与 token 校验（内置注册 + 外部文件加载：env `MD2VIDEO_STYLE_PACK_FILE` 指向 ThemeTokens JSON，`get_pack` 解析路径上惰性加载一次，坏文件/缺文件/重名 fail fast，未知名降级 + warning）。
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

- [x] `ScenePlan.layout_regions` 直接提案入口（与模板走同一套属性校验；设置时优先于 layout_type；名为 image 的 region 是可出血视觉槽位）。
- [x] 结构化 LayoutIssue：code + region + 数值差 + 修改建议，一次报全部问题（`layout/constraints.py`）；pipeline fail-fast 的报错包含全部 scene 的全部 issue。
- [x] 约束注册表（零特权 `register_constraint(fn)`，内置与外部规则同一通道；env `MD2VIDEO_LAYOUT_CONSTRAINTS` 显式加载 Python 约束模块，导入失败 fail fast；pack JSON 永不被执行）。
- [x] 子构图 region 化：section header 左列堆叠改由模板子 region `section_stack` 表达，渲染器只装内容。

验收：非法提案得到可执行的结构化报错；现有模板路径行为不变。✅（2026-09-06：结构化报错含全部 issue 测试全绿；smoke 计划与 example 端到端改前后 framemd5 逐帧全等）

### A6 混合引擎（按 scene）

目标：不同 scene 用不同渲染引擎；Remotion 作为第一个真实第二后端。

- [x] scene 级 `render_backend` 字段（空 = 用 `ToolConfig.render_backend`）；要求的后端未注册时开渲前 fail fast。
- [x] 按 scene 分组分发：相邻同后端 scene 组成极大组；plan 切片 → 各后端 → N 段视频 + N 份局部 timeline（`core/multi_backend.py`）。
- [x] 视频拼接（concat filter，全静音 run 出无音轨底片走 assembler 已验证静音路径）+ timeline 前缀和偏移合并 → 重过全局闸门（对完整 plan 跑 `check_timeline`）。
- [x] 组边界状态策略：引擎切换即场景切换，每组独立渲染调用，渲染器内部跨 shot 状态（字幕堆叠/母题）清零。
- [x] Remotion 后端：同一渲染契约 + 自带 Realizer + 能力词汇声明（动效意图、母题 kind）。（决策 2026-09-07：第二后端只做 Remotion；HyperFrames / 云渲染 API 不做专项评估，留 Idea Pool。）

验收：混合 manim/remotion 的 plan 出一条成片；Remotion 通过全部闸门。A6 前半验收（2026-09-07）：混合 manim/fake 的 plan 出一条成片且过全部闸门（真 manim 组 + fake 组，env-gated smoke）；全部 fake 的多组 run 出片过闸门；单一 manim 后端的 plan 行为与现状完全一致（example 端到端 framemd5 逐帧全等）。A6 后半验收（2026-09-07）：`RemotionRenderTool`（契约同 manim_tool：五字段进 / 五字段出 + 后端自跑时间闸门）+ 纯函数调度器 `remotion_schedule.py`（音频事实 + pack 节奏推导，动效不消耗时间窗口为已记录差异）+ Node 侧 composition（`tools/render/remotion_backend/`，能力词汇：reveal write/fade/appear、dismiss instant/fade、motif orbit_dots，词汇外降级 + warning）；`test_remotion_backend.py` 13 项单测；env-gated 真渲染 smoke（`test_remotion_smoke.py`）：remotion 单后端出片（480x854、时长与调度一致、标题/正文按 layout 区域像素落位、双跑 framemd5 逐帧一致）+ manim/remotion 混合 plan 经 multi_backend 分组渲染拼接出一条成片（render_provider "manim+remotion"）。补验（2026-09-08）：CLI 全链路真跑出片（配音 + Remotion + 装配），并修复三个集成 bug（相对路径解析、`ffprobe_resolution` 尾部空字段、before/after 锚点 cue 不落 timeline markers），回归测试随之补齐（`test_remotion_tool_resolves_relative_paths_against_caller_cwd`、`test_ffprobe_resolution.py`、`test_before_and_after_marker_cues_reach_timeline`、`test_unanchored_after_marker_clings_to_own_shot_end`）。带图+BGM 的 `example.md` 走 Remotion 完整出片：图片/Ken Burns 与 BGM 由后端无关装配层按 timeline marker 叠加，正文由组件按 region 落位，引擎内不重复画图。

### A7 内容槽位（按需阀门）—— 挂起

识别归 infra（parser/schema/降级规则），表现归 pack。只在 B 系列包需要时激活。

状态：**挂起**。理由：当前 markdown 识别够用；内容表现优先走「组件注册 + 口播 skill」主线——agent 经 `--plan` 直产 plan 时绕开 parser 拍平，列表可由 agent 直接拆成独立 segment。重启时注意：三块工作中只有「引擎表现原语」可走组件路线；「识别」（新 segment 类型会流经 TTS/planner/renderer/assembler，契约宽度远超表现组件）与「pack 槽位」（ThemeTokens schema 扩容）只能改 core/schema，组件路线不省这两块的成本，不必等 A8。

已知未修边界（挂起期间接受）：md 入口下列表符号被 segmenter 当标点剥掉、`**加粗**` 星号可能漏进画面文本；如需最小卫生修可做 parser 归一化（拍平列表、剥 emphasis 标记），暂不排期。

- [ ] parser 识别列表/加粗/引用 → 新 segment 类型；不支持的 pack 强制降级 + warning。
- [ ] 表现语义（列表逐条浮现、金句、引用样式）由 pack 提供。

验收：带列表/引用的 markdown 出片；不支持的 pack 干净降级。

### A8 组件注册（提案 → 契约验收 → 入库）

门槛就是契约本身，**不设人工审核环节**；验收入口是纯 infra CLI，不依赖 harness，交互回路留给未来 harness，契约不变。契约在第二个真实后端（Remotion）落地后才定义，避免只有一个引擎时长成 manim 形状——该前提已满足。

契约：表现组件 = 接管一个 scene 正文画面的 Remotion 组件。**输入 = 文字 + 每段可见窗口 + 画布尺寸；输出 = 自由画面**——配色/字体/排版/动效由组件自带，不消费 pack token（创作自由度优先于全片换肤一致：终端展示本该自带绿字黑底）。pack 与组件的分界：换个 pack 跟着变的归 pack（全片气质），不变的是组件（一类内容的演法）；pack 的动效意图只作用于引擎默认渲染的画面。两条底线：①组件不改时间事实——可见窗口由调度器按音频事实裁决，音频绑定留在 wrapper，时间闸门不豁免；②确定性渲染——禁 random/网络/fs，双跑逐帧一致。已接受的代价：组件场景的 layout 合法性由上架时的黄金帧验收承担（运行时机器检查只覆盖引擎渲染的画面，组件与场景风格不另设运行时检查）。

接入方式：组件按 scene 挂载、按 shot 窗口渲染（`ScenePlan.component`，空 = 引擎默认，与 `render_backend` 同构）；plan 引用 `id@version`，不搞浮动最新版；未知组件 id 降级默认渲染 + warning；声明组件但 scene 落入 manim 组 fail fast。v1 只开放 body 表现；标题卡与 section 堆叠字幕仍归**引擎绘制**、样式归 pack。分工：组件针对 shot——逐 shot 窗口渲染正文画面；scene 满足风格——风格单位，声明本组 shot 用哪个组件。组件注册一次、处处引用；需要画面连续的内容（如数学演算）由切镜保证——连续段放进同一个 shot，组件在该 shot 窗口内从头画到尾。**A8.1 修订（2026-09-14）**：①section header 段允许写进组件场景作为预热窗口（动画从 header 旁白起笔），z-order 相应对调——**header 恒画在表现组件之上**（title_main/sub 仍禁止进组件场景）；②`visual_params` 随组件场透传进组件 props——它是 plan 作者写给组件的 scene 级编排数据（如 math_canvas 的图层锚点），组件自己声明并校验词汇，非组件场 payload 零变化。

layout 冻结：不再加模板、不加功能，新表现力一律走注册组件；运行时不新增 layout/风格检查——组件的上架验收（check-component）是唯一关卡。

- [x] 组件注册表 + 显式模块加载（env `MD2VIDEO_COMPONENTS`，A5 模式：代码只经显式 import，pack JSON 永不执行；同 ref 同内容幂等、异内容 fail fast；相对路径按调用方模块目录解析）。
- [x] `ScenePlan.component` 字段与裁判（格式错误与跨后端使用 fail fast；未知 id 留给渲染层降级 + warning，无组件 run 的调度 props 零改动）。
- [x] 调度器为组件 scene 产出 payload（ref 随 shot 下发；未注册/未安装降级 + warning，不静默落到 Node 缺省）；Node wrapper 按 shot 窗口挂载（绝对时间语义，音频绑定留 wrapper，标题与 section 堆叠仍归引擎）+ 生成 barrel + 缺省回退。
- [x] 验收入口 `python -m md2video.check_component <module>`：禁用 API 静态扫描 → staged 安装 → fixture plan（标题 + 三段静默正文）真渲染两遍 → timeline 逐字节 + framemd5 逐帧一致 → 黄金帧（首轮存档、复核逐字节比对）→ 全过提交安装，失败回滚不留痕（installed = registered；安装后内容漂移 fail fast）。
- [x] 首批技术向组件走完全流程入库：`step_list@1.0.0`（步骤列表逐条浮现）、`code_display@1.0.0`（GitHub-dark 代码面板：行号 + 极简语法着色）、`terminal@1.0.0`（终端黑窗口，`$` 前缀段渲染为命令行）。

验收：外部写一个表现组件，check-component 通过后在 plan 中引用出片；故意破坏组件使闸门失败时被拒且报错可定位。

已完成部分验收（2026-09-12）：三个首批组件各经 `python -m md2video.check_component` 真验收通过（双跑 framemd5 逐帧一致、4 张黄金帧入库），step_list 另做像素级确认（自带深板岩底 ≠ 引擎黑底）；env-gated 冒烟覆盖三个组件的复核路径；全量 `621 passed, 5 skipped`（skip 均为 env-gated 真渲染）。

另一议程（暂缓）：是否增列「内容识别插件」为第四类组件（即 A7 识别的组件化路线）——新 segment 类型流经 TTS/planner/renderer/assembler，契约宽度远超表现组件。

### A8.1 场景画布（按场挂载的组件）—— 已落地

动机（2026-09-12 拍板）：对标 3b1b 的画面累积感——单位圆画完，切走讲别的再切回来它还在，新镜头往上添一笔。现状做不到：组件逐 shot 挂载、每镜重启、画面清空，镜头之间画面是断的。这是数学 showcase 片的前置能力。

核心语义：**场 = 画面状态的单位（画到哪了归场管），shot = 访问画面的时间片（什么时候看归 shot 管）**。同场 shot 允许散在片子的不同位置（既有语义不变）：画布在时间上不连续，但状态必须连续——切走期间画布不播，状态不丢。

设计六点（2026-09-12 与 owner 对齐）：

1. 挂载方式记在组件注册表里（注册时声明「按 shot 挂」或「按场挂」），plan 格式不动——`ScenePlan.component` 仍只写 `id@version`，planner 无感知，老 plan 全兼容；组件作者决定自己的生命周期。
2. 输入升级：按 shot 挂的组件照旧只拿本镜窗口；按场挂的组件拿到**整场镜头时间线**（每个 shot 的起止 + 段落文本 + 声音起止）+ 自己排第几，演化节奏是组件内部逻辑，管线不管。
3. 状态累积是纯函数推导，不靠运行时记忆：组件根据 cue 表算出「轮到我这个镜头时画布上该有什么」（此前镜头累积 + 本镜新增），每个 shot 窗口一个实例、各自渲染累积状态。确定性渲染，双跑逐帧一致，check-component 可验收。
4. **不加任何连续性检查**——镜头散开是合法且预期的用法，恰好演示「切走再回来，画面还在」。（初版设计曾提「同场镜头须时间连续否则 warning」，已收回。）
5. 画布只接管正文区：标题与 section_header 仍由引擎按 pack 画，组件不碰品牌一致性（与 A8 现有分工一致）。
6. 渲染结构无新机器：仍是一个 shot 窗口一个实例、绝对时间定位，只是组件能「看到全场」。

补充语义（实现时确立）：plan.scenes 允许**同一 scene id 复现**，表示「回到这场」——执行顺序是逐 scene 扁平化，复现条目的 shot 天然插进别场之间；调度器按 scene_id 把两次访问收拢成同一条画布时间线。plan schema 零改动（scenes 列表本无唯一性约束）。

- [x] 契约落地：`register_component(..., mount="shot"|"scene")`（注册表声明，manifest 携带 mount、旧条目缺省 shot）；调度器 `_annotate_scene_canvases` 为按场挂 scene 的每个 shot 附 `scene_shots`（全场镜头时间线）+ `scene_shot_index`；Node wrapper/types 透传（`timeline` 事实保持精简不带画布字段）。
- [x] check-component 按场模式验收夹具：组件场 → 普通场 → 组件场（scene id 复现，shot 不邻接），双跑逐帧一致 + 黄金帧。
- [x] 试点组件 `math_canvas@1.0.0` 入库：坐标系底座 + 单位圆/正弦/余弦按访问次序叠加（SVG stroke 画线动效），4 张黄金帧。
- [x] skill 文档补：组件货架加挂载列 + `math_canvas`；「切走再回来」写法（scene id 复现示例 JSON）；切镜规则加跨镜头累积一条。

验收：✅（2026-09-13）`python -m md2video.check_component md2video.components.sources.math_canvas.register` 通过——按场夹具（scene_001 复现被 scene_002 隔开）双跑 framemd5 逐帧一致；黄金帧目检确认第二次访问（t=6.0s）画面包含第一次访问累积的单位圆 + 新增正弦曲线（时间不连续、状态连续）。单测：registry mount 校验/幂等/manifest roundtrip/旧条目缺省 shot（5 项）+ 调度器 scene_shots/复现收拢/按 shot 不带画布字段（3 项）。全量 `629 passed, 6 skipped`。普通按 shot 组件 payload 零变化（无 scene_shots 字段）。

showcase 首片（2026-09-13）：`evals/trig_circle.md` 经 skill 产 plan 出片 **65.7s**（20 段 / 11 场 / 18 段配音 / 零 warning，`artifacts/trig_circle.mp4`）。`math_canvas` 场景在 plan.scenes 里复现三次表达「回到这场」，中间被文字场真实隔开（8.0s / 22.1s / 37.9s 三次访问）；抽帧目检确认累积叙事成立——访问一只单位圆，访问二圆仍在 + 正弦叠加，访问三再叠加余弦，3b1b 式「切走再回来画面还在」在真实成片里生效。

### A9 OTIO 导出（交付形态，infra）

决策（2026-09-07）：OTIO 导出归 runtime/infra（timeline 事实的另一种 serialization），不是 harness 功能。

- [x] `timeline.json` → OpenTimelineIO 纯函数 lowering + 结构黄金测试；经 OTIO 适配器可达 EDL / FCPXML / AAF 生态。
- [x] result.json artifact index 登记 OTIO 产物。

验收：✅（2026-09-07）`timeline/otio_export.py` 纯函数 lowering（shots→Video track Clip、marker→所属 shot Clip 上的 Marker、text 事实→Clip metadata、无可归属条目→Timeline metadata 孤儿区、fps 优先取 timeline 携带值可扩展多帧率）+ `test_otio_export.py` 11 项测试（结构/序列化确定性/roundtrip/坏条目容忍/库缺失与失败降级/管线 artifact_index 登记）全绿，全量 `565 passed, 2 skipped`；opentimelineio 缺失或导出失败时降级为 warning，不阻断 MP4 交付。真文件级验证（2026-09-08）：对 example.md 真实 run 的 `timeline.otio` 做独立读回校验 19/19 通过（fps 经 `global_start_time.rate` 可读——为此给导出补了 `global_start_time=RationalTime(0, fps)`，外部 NLE 导入器习惯从这里取时间线帧率；clip↔shot 起止逐项对齐；marker 挂所属 clip 且时码对齐；text 事实 21 条全进 metadata；roundtrip 字节一致）；另装官方 `otio-cmx3600-adapter` 把真文件转成 CMX 3600 EDL 成功（4 事件对 4 shot、marker→LOC 注释、时码帧量化正确），证明第三方 NLE 生态可消费。残留：Resolve 真机导入验证属一次性人工检查（不进 CI），未执行。消费级剪辑软件直连实测（2026-09-12，GUI 实机操作）：本机仅有的两款——必剪（导入过滤器仅 mp4/mov/avi/rmvb/f4v/mkv/m4v/flv/mpg/gif/rm + mp3/wav/m4a 等媒体格式，手动输入 timeline.otio 与 timeline.json 完整路径均弹「文件导入失败」）与 Clipchamp（选择器过滤器为所有文件，但仅接受视频/音频/图像/GIF，.otio 与 .json 均被静默丢弃）——均无法直接打开 OTIO 或裸 JSON；结论：面向消费级剪辑软件的交换路径走 CMX 3600 EDL（已验证可转换）或直接交付成片，OTIO 面向的是专业 NLE（Resolve/ Premiere+插件）生态。

### A9.1 混剪素材包 bundle 导出（解法 1+4，交付形态）

决策（2026-09-12）：消费级剪辑软件（必剪/Clipchamp 实测）无法直接打开 OTIO/JSON，面向用户的编辑交付走「混剪素材包」；EDL/OTIO 是零成本基础设施备胎，不当用户功能宣传。成片永远是第一交付物，bundle 失败只降级为 warning。

- [x] `timeline/bundle_export.py` 纯函数导出（默认关，CLI `--bundle` 开）：`subtitles.srt`（text cue 白名单 content/appendix，挂屏标题类排除）+ `timeline.edl`（复用 otio lowering 转 CMX3600）+ `clips/shot_*.mp4`（按 shots 边界重编码切成片，流拷贝会按关键帧漂移故不用；末端截到成片实际时长）+ `assets/`（声明图片/BGM/每段配音拷贝）+ README。
- [x] 管线接线：`Pipeline(export_bundle=True)` → run 目录 `bundle/`，登记 `result.json artifact_index["bundle"]`；任何子步失败折进 run warnings，不阻断成片。
- [x] 测试 `test_bundle_export.py` 9 项：SRT 时码格式/黄金/过滤与容错、bundle 文本产物确定性（逐字节）、EDL 独立读回（cmx_3600 适配器；注意注册名带下划线；CMX3600 不携带可靠帧率，跨实现只断言结构与文本级 30fps 帧时码）、真 ffmpeg 切片帧级精度与时长截断、管线登记与默认关闭。全量 `592 passed, 4 skipped`。
- [x] 真 CLI 冒烟（remotion 后端，example.md）：run `20260912-144901-0a6714` 产出完整 bundle——SRT 16 条口播（标题正确排除）、4 个切片（1.0/10.13/18.2/37.2s，与 shot 边界帧级吻合）、19 条配音 + BGM + 封面图、EDL 四事件时码正确。

验收：✅（2026-09-12）④ 实机验收通过——必剪与 Clipchamp 各建工程，GUI 导入 bundle 三类素材（clips/shot_002.mp4、assets/images/cover.jpg、assets/audio/seg_003），素材池各出现一条（必剪 全部(3)=视频1+图片1+音频1；Clipchamp 三项入库且 mp4 被自动托到时间线放置区）。实测抓到并修复一个真 bug：edge-tts 产物名为 .wav 实为 mp3 内容，必剪按扩展名验格式静默拒收——`_copy_assets` 拷贝前按魔数（ID3/FFxx/RIFF-WAVE/OggS/fLaC）识别真实容器再定扩展名，含回归测试。另一已知边界：文件框一次输入多个引号路径会被两家的对话框截断到前两个（与 bundle 无关，逐个导入即正常）。SRT 本机无软件可导（剪映/PR 才支持），只做格式级校验。时间线层定位不变：消费级=人工按序拖切片，剪映=解法3 草稿注入（挂起），专业=EDL。遗留现场：必剪测试草稿 202609091423 内有 3 条导入素材、Clipchamp 有测试工程「Video Project」（用户示意不必清理）。

## Track B: 自研设计包

目标：框架自带"开箱能看"的参考设计，并验证社区包路径。包 = 纯数据宣言（palette/typography/motion/motif 槽位），不含引擎代码；引擎与包正交，能力按名字引用。

### B1 Reference Pack（与 A2 同一里程碑）

- [x] 现有 house style（黑底白字仿宋 + 圆点母题 + 现节奏常量）抽取为 `ink_night` pack。
- [x] 与 A2 联合验收：像素逐帧不变。✅（2026-09-06）

### B2 知识口播 skill

- [x] 口播 skill v1（`skills/voiceover/SKILL.md`）：给 planner agent 的一篇文档——内容套路（结构模板：钩子/分段/节奏；切镜规则：需要画面连续的内容切进同一个 shot）、组件货架（注册组件的 id + 适用内容 + 例子，agent 按内容挑并写进 scene）、命令用法（--plan 全流程）、读 viewer + warnings 迭代、缺组件时走组件提案流程。首片验收（2026-09-12）：`evals/git_internals.md` 经 skill 产 plan 出片 71s（17 段配音、三个组件全部正确挂载、零 warning）。跑出的契约坑已写回 skill：**要朗读的 segment 必须显式带 `audio_request`**（缺 = 静默段，管线不读也不警告——首跑曾全片无声）。遗留：①组件"显示文本 ≠ 朗读文本"（代码/命令类组件的口播听感）需要契约扩展，待排期；②正文 15px 偏小的读片意见归 knowledge pack 触发条件。
- [ ] `knowledge` 风格 pack（暂缓）：首片读片后若引擎默认画面拖后腿，再把节奏 / 字号梯度 / 母题调成 knowledge pack——pack 全片级、配置选择，不进 skill 的选择面。

分工：流程归代码（CLI / 管线 / 闸门）；场景演法归组件（agent 按内容挑，自带视觉，pack 不引用组件）；全片气质归 pack（配置级，现默认 ink_night；第二套气质出现时再考虑写进 plan 头部使 plan 自描述）；内容套路归 skill 文档。

验收：一篇技术向知识 markdown，经 skill 产 plan 出"至少能看、不划走"的片（近期主线的 eval 样例）。

### B3（远期）第二套风格

- [ ] 外部结构落地第二套 pack，验证"社区包与内置包零特权差别"。

## 成片质量冲刺——知识区格式（2026-09-13 定调，同日修订）—— P0/P1 已完成（2026-09-14 收官）

背景：架构收官（两条零 warning 成片：git_internals 71s、trig_circle 65.7s），但**成片质量距离"能发出去"差距很大**。owner 读片定调（2026-09-13）：**知识区口播片的格式 = 画面（图/图示/演算）+ 烧录字幕 + 解说 + BGM**——图片是画面主角，字幕是文字的唯一载体；我们两条片本质是黑底文字卡，加字幕、调字号都是润色，**主线是换格式，不是润色**。

架构结论（已核）：**本批零架构改动**。图片在契约里是 execution-assets（scene `visual_type`+`visual_params` → 视觉工具产图 → 装配层按 timeline 叠加，Ken Burns 与图文模板现成，2026-09-08 带图+BGM 已真跑通）；BGM 走 marker；演算画面走组件货架。**代码生图与 AI 生图地位相同——都是注册一个视觉 tool**，产 execution-assets、不碰 timeline。唯一真正的新代码是烧录字幕（装配层叠加，四本账与闸门不动）。竞品调研（MoneyPrinterTurbo ~56K★、ShortGPT、markdown_video、TheoremExplainAgent）确认缺口项均为竞品验证过的标配；我们的差异化 = 确定性编译器 + 组件货架（"LLM 现写渲染代码"路线的反面）。

### P0 知识区格式（本轮施工）

- [x] **代码生图 tool**：`GenImageTool`（provider="procedural"，visual_type `gen_image`）——PIL 确定性绘制四种母题（orbit/layers/waves/blocks），prompt 哈希作种子（跨运行逐字节一致），三套深底调色板，图内不渲染文字（文字归字幕与解说）；ToolCache 缓存（generator 版本号进 cache_key，改绘制即失效）；style/palette 拼错 fail fast 走既有「工具失败→warning+降级」通道；管线默认注册 + 优先级表 `gen_image: ["procedural"]`。AI 生图（text2image）留同一 visual_type 口子。验收：✅（2026-09-13）14 项单测（确定性逐字节/契约字段/缓存命中/校验 fail-fast/注册接线），四母题 480x854 样本目检通过；全量 `643 passed, 6 skipped`。
- [x] **烧录字幕**：timeline text cue → ASS（libass）→ 装配器尾部叠加（字幕永不被图片遮挡）；定位为**文字的唯一载体**。关键事实与决策：①白名单 content/appendix（与 bundle SRT 一致），标题/header 不进字幕轨；②只上**真被朗读的段**（音频资产事实优先，缺位回退 plan audio_request）；③实测当前 libass（0.17.4 directwrite）对无空格中文长句**不断行、直接裁边**→构建期按像素宽度手动折行（行首避标点）；④任何字幕问题只降级不阻断成片；⑤`--subtitles` 旗标默认关（不破坏既有产物逐帧一致性），knowledge pack 接管样式后议默认开。附带修复：`math_canvas@1.0.1` 移除画布解说标签（与字幕物理重叠，字幕上位后标签退场）、水印挪顶部，check-component 重验收 4 张黄金帧。验收：✅（2026-09-13）10 项单测（含真 ffmpeg 像素级字幕验证）+ trig_circle 重渲 14 条字幕目检（三场型：画布/组件/文字）；抓到并修复折行清空 bug（11 字句字幕变空气）；全量 `653 passed, 6 skipped`。
- [x] **BGM 接线 + skill 套路升级**：marker/BGM infra 现成——skill 结构套路补三件事：按段落配图（`gen_image` 的 prompt/style/palette 写法）、BGM 段落（declaration + `music_start` cue）、字幕观感自查。踩坑写回：**plan 手写 cue 必须带 `id`**（闸门与装配器靠它对账，漏了报 `Timeline missing marker cue time`）。BGM 资产本身也走代码产：`evals/assets/make_bgm.py` 合成 20s 无缝循环垫乐（颤音周期整除循环时长，相位连续）。
- [x] **验收片**：`artifacts/trig_circle_kf.mp4`（65.7s）——**解说 + 程序化插画 + 字幕 + BGM 四样齐**的知识区格式片：钩子/结尾两场 `gen_image` 满屏插图（orbit/waves，Ken Burns），三场 `math_canvas` 演算，一场 `step_list`，14 条烧录字幕，BGM 从标题后铺到片尾（自动压低成垫）。渲染中抓到并修复：①`gen_image` 曾返回相对路径，`--plan` 场景装配器按 plan 目录解析导致图片被静默丢弃——工具改返回绝对路径（TTS 先例）+ 装配器相对路径解析加 cwd 回退 + 缺图从静默丢弃改为显式告警；②owner 读片指出插图 Ken Burns **持续抖动**——`zoompan` 按输入像素格点取整（第一层），且超采样后仍周期性顿挫（第二层，取整后每 3~4 帧才挪一格）。修复 = **超采样 4x → zoompan 保持超采样尺寸 → lanczos 缩回区域**（取整停在细格点、缩放插值保住亚像素运动）；像素级验证：连续 40 帧 0 对相同、帧差均匀 0.29~0.50（此前 md5 测量歧义曾误导，以解码像素比对为准）。

推迟观察两项已在文字层改版中落定（见下）；**标题卡可见性**与**文字层策略**均按读片结论转正实现。

- [x] **文字层改版 A/B/C**（2026-09-14，仅 Remotion 后端，manim 记已记录差异）：**A 标题退场**——title payload 携带 `end`（= title_hold，第一个正文镜头开始），wrapper 淡出标题卡，标题只在片头出现一次（旧 payload 无 end 时退回全程可见，向后兼容）；**B 正文去重**——朗读段（有音频绑定）不再由引擎画正文，字幕是文字的唯一载体，静默段正文保留；**C 章节牌**——section header 从裸灰字升级为 accent 竖条 + 半透明底板的牌照式，且窗口改从 timeline text facts 取（开放到下一个 header，与 manim 堆叠语义一致——旧实现用 shot 段自身音频窗口，牌念完 2.5s 即消失立不住）。帧验证：t=3 钩子场标题已退、只剩插画+字幕；t=42 章节牌常驻带牌面。

### P1 主线（货架生长）

- [x] **math_canvas@1.2.0**：动点 + 投影 + **图层锚点数据驱动**。读片迭代的收敛：1.1.0 动点版（角度由累积活跃时间驱动，切走冻结/回场续转）→ 1.1.1 owner 否决"波和点各转各的"——**波是点的高度投影**：角速度由 cue 表推导为"正弦锚点窗口结束恰好转完第一整圈"，描线比例 = θ/2π，正弦波头与动点严格同高（水平投影虚线），波幅 = 半径 → 1.2.0 owner 定调"图层编排归 plan 作者，不落代码"：**`visual_params.layers`（{shot, kind} 锚点声明）随组件场透传进组件，组件不猜**；header 段可写进组件场景（预热窗口，动画从 header 旁白起笔，z-order 对调 header 恒在组件之上）；余弦改为**半径三角构造**（圆心→垂足横线段 = 点的水平位置，纵轴对应点到波头投影虚线）；wrapper header 改从 timeline text facts 取窗口（开放到下一个 header，与 manim 堆叠语义一致——旧实现用 shot 段自身音频窗口，章节牌念完即消失立不住）。帧验证：header 场动画起笔、余弦半径三角、章节牌跨窗口常驻。
- [x] **math_canvas@1.3.0**：**章节化角度**（读片第四轮收敛）。1.2.0 的图层锚点仍有一个时序缺陷（owner 指出）：描线比例挂在全局 θ 上，余弦波在正弦解说的 shot 里就提前描了大半——描线与解说脱钩的残余。1.3.0 语义：**动点一章转一圈**——章节 = [场起点→锚点1]、[锚点1→锚点2]、…、[锚点n→场尾]，θ 分段线性（每章恰一整圈，切走冻结/回场续转保留）；波只在**自己的章节内**随动点描出、章末描满保持；章边界 = 切镜点且动点恰回最右（cos 2π = cos 0）→ **跨 shot 动画连续无跳变**（owner 的核心诉求）。帧验证：t=24 正弦章半程、t=30 章末归零、t=34 余弦章起笔、t=45 描满。
- [x] **math_canvas@1.4.0 + step_list@1.0.2**（读片第五轮）：owner 指出①总结列表步骤 2/3 之间错位——step_list 固定行距装不下两行换行文本，**行距改按换行行数动态累计**（估算每行字数 × 行高，步进式布局）；②余弦视觉杂乱看不明白——**聚焦降杂**：已描满的历史波层降暗至 0.3、当前章满亮度，去掉垂足圆点装饰，构造元素只留必要的投影线。两组件重验收 + 重渲帧验证（t=40 聚焦效果、t=53/58 三行无重叠）。
- [x] **math_canvas@1.5.0**：**余弦竖排构造**（读片第六轮）。owner 点破 1.4.0 的根本缺陷："动点的横着的部分没有很好地对应产生的曲线"——余弦波横排时，波头高度 = 点的横坐标，观众每帧要做 90° 心理旋转，画面不给任何帮助（半径三角是补偿但补不回来）。1.5.0 采用 3b1b 原始构造：**余弦波竖排**——从圆心高度垂直向下，波头横偏移 ≡ 动点横偏移（同基数同振幅），连接两者的投影虚线是**垂直的**，点的横向摆动直接就是下方波的左右摆动，零心理旋转；与正弦章（横排波+水平虚线=高度投影）形成对称："余弦是正弦转 90°"在画面构造上字面成立。帧验证：t=42.8 垂直虚线严格竖直、章末波完整闭环。
- [x] **拆 3~5 支知识区对标片**：以文字资料级拆解完成（3b1b Chapter 3 七段式结构 + 幕后 updater 语法 + 知识区/代码区语法；受限于无法逐帧看外部视频，拆到"镜头语言清单"粒度）。**组件候选清单**（按优先级）：①持续微动效默认态（静帧是最大观感差距，非新组件而是演法要求）②label_pin 标签随动（画布内原语）③ghost_transform 变换原语（旋转三角形类构造镜头）④highlight_code/code_display 2.0（逐行高亮+光标）⑤arrow_note 箭头标注层 ⑥音效点（marker 扩 kind=sfx）⑦area_fill 区域填充 ⑧画布内镜头控制。详见 `docs/competitive-research.md`（含四赛道竞品调研归档，P3 归档项同步清账）。

验收口径（原定）：本批做完出一条「解说 + 程序化插画 + 字幕 + BGM」四样齐的知识区格式片，做到"陌生人刷到不划走"。每项独立可验收，顺序即优先级。**执行结果（2026-09-14）：四样齐达成，"不划走"未达标**——原 P2/P3 条目按新定调重排，见下节。

---

## 下一批：demo 整改 + 开源展示（2026-09-14 定调）

背景：知识区格式四件套已齐、math_canvas 六轮读片迭代至 1.5.0，但 owner 读片定调：**成片仍未达标**。同日目标收敛：**实际目的是开源发布——多攒工具与能力，尽快向别人展示框架的潜力**；demo 现状不行。agent 视觉读片首例（coding agent 抽帧 12 帧全片体检 `trig_circle_kf`）结论：**不是路线问题，是具体策略/实现问题**——4 个 bug 级 + 2 个短板，全部低成本可修。读片回路定为：**coding agent 抽帧承担**（owner 只看标记帧），VLM 读片助手不再立工具项。

### 读片体检结论（2026-09-14，trig_circle_kf；bug 级 → 短板级）

1. ❌ **字幕与组件显示文本逐字重复**（step_list 总结场）——文字层 B「正文去重」只覆盖引擎正文，未覆盖组件自带文字，同一句话观众看两遍。
2. ❌ **组件水印泄漏成片**（`math_canvas · chapter 1/3`）——组件 id 像调试信息，开源 demo 减分。
3. ❌ **标题卡版式**——标题挤顶部 1/4、下方 3/4 空黑；副标题疑似溢出被静默裁字（「讲透正弦和余[弦]」）。
4. ❌ **字幕 CJK 折行质量**——词中断行（「高/度。」）+ 孤字成行（「圈。」「零。」）；现有「行首避标点」不够。
5. ⚠️ **标签牌与图形无避让**（正弦章牌子压波形）——label_pin 问题域。
6. ⚠️ **静帧**（总结场除入场外全静）——微动效问题域。

### P0 demo 整改（bug 级，先做，全部低成本）

- [ ] **字幕 / 组件文字去重**（决策已定 2026-09-14）：**组件显示且被朗读的文本，字幕轨跳过该段**（组件文字即该段载体），回退 = 朗读且无组件文字才上字幕。层级归属：**装配层字幕选段策略**（与 content/appendix 白名单、「只上真被朗读的段」同层同性质的第三条规则）；契约层配套小声明——组件注册契约增加 `displayed_texts(payload)` 纯函数（确定性比对来源，check-component 可校验）；组件本身不改（A8 底线：组件只画像素，不碰时间与装配）；timeline text facts 保留不删（组件显示它也是可见事实），仅装配消费时跳过；skill 补一句防误报。与文字层 B 的分工写进 docs：**文字载体归组件时，字幕让位**。
- [ ] **组件水印退场**：组件 id 不进成片；章节指示如需保留，改纯数字/章节名样式，去掉 `math_canvas` 字样。
- [ ] **标题卡版式 + 溢出闸门**：标题卡构图重做（垂直居中或上 1/3 + 下方配画面元素）；文本溢出**从静默裁字改为构建期告警/换行 fail fast**——「看似有效但内容被裁」正是契约该拦的。
- [ ] **字幕折行升级**：CJK 避词断行（不在词/字组中间断）+ 末行孤字回填（孤字不单占一行），叠在现有「行首避标点」之上。
- [ ] **整改验收**：重渲 `trig_circle_kf`，agent 全片复检，对照本清单逐项销账。

### P1 观感补强（demo 不「像 PPT」的关键）

- [ ] **持续微动效默认态**：任何静止超过一屏的画面有低幅呼吸/漂移——不是新组件，是组件演法默认要求（对标拆片确认的最大差距）。
- [ ] **label_pin 标签随动**：轻量版可先做「标签与图形避让」（即体检问题 5），随动版归 math_canvas 扩展。
- [ ] **音效点**（marker 扩 `kind=sfx`）+ **前 3 秒钩子场强化**（可选触发）：划走与否看前三秒。

### P2 开源展示物料（目的：向别人展示框架潜力）

- [ ] **MCP 工具化**（自旧 P2 提前）：plan 校验 / check_timeline / check_component 已是纯函数 CLI，包成 MCP server 让任意 coding agent 直调——"agent 原生自带验收工具箱"的活 demo；markdown_video 的 MCP server（10 工具）验证了此路产品价值。
- [ ] **README 定位重写 + GIF + 门面片**：确定性视频编译器 / agent 可操作 / 组件生态，正面对着"LLM 现写渲染代码不稳定"的赛道痛点讲；GIF 素材 = math_canvas 画布累积段；门面片 = 整改后的 trig_circle_kf。
- [ ] **code_display@2.0 逐行高亮 + 光标**：开源受众是开发者，代码 demo 是主场（也可做代码样例片时触发）。
- [ ] **样例片矩阵 2~3 条**：数学演算 / 代码讲解 / 概念流程各一，展示货架宽度，每条 60~90s；题材 owner 定。

### 可选 / 按需（原 P2/P3 重排后）

- [ ] **AI 生图 provider**：text2image 注册为视觉 tool（同 gen_image 同一口子，产 execution-assets 不碰 timeline）；owner 表示可有 key 但非重点，插图质感冒尖再上。
- [ ] **knowledge pack 重定义**（字幕样式 / 图片柔影圆角 / 口播节奏）：字幕已是文字唯一载体，样式权重升高；P0 若需要可先拆字幕样式最小版。
- [ ] **Kokoro 本地 TTS 备选**：先做半天「音色/语速对比实验」评估 edge-tts 机器味伤不伤，再决定投不投。
- [ ] **ghost_transform / area_fill / 画布内镜头控制**：做几何样例片时触发（题材向，不排通用队）。
- [x] ~~竞品调研落盘~~ ✅（已归档 `docs/competitive-research.md`，commit 6876f29）。
- [x] ~~VLM 读片助手~~ → **取消立工具项**：读片回路由 coding agent 抽帧承担（本批体检即首例）；将来片量大再议最小筛帧脚本。

验收口径：P0 验收 = `trig_circle_kf` 重渲后 agent 复检、逐项销账；P2 验收 = MCP live demo + README + GIF + 门面片可对外演示。顺序即优先级。

## 里程碑与依赖

依赖链：**A1、A2.5 随时可做；A2 + B1 绑定落地 → A3（静默节奏来源 = pack motion token）→ A4（viewer，B2 调参受益）→ A5 → A6**。已按此顺序全部落地（A9 / A9.1 随后完成，2026-09-07 ~ 09-12）。breaking 迁移只有 A3 一次。

近期主线（2026-09-12 收官）：~~LLM planner 前缀修复~~、~~A8 组件管线（契约 + 注册表 + check-component + 首批三组件入库）~~、~~口播 skill v1（以 B2 验收为 eval）~~ 全部 ✅。原则：agent 产码过闸入库、运行中不现写代码；组件管画面、调度管时间。A7 挂起（识别与 pack 槽位将来重启时走 core/schema，不等 A8）。

## Future: Harness / Agent Workflow Layer

这些属于未来 harness/workflow，不应该混进当前 runtime 交付。

本节属于未来 harness/workflow，不混进当前 runtime 交付。「口播 skill」的最小版是例外：它已升为近期主线（见 B2 与「里程碑与依赖」）——skill 是 agent 侧的 craft 文档 + 工作流，不给 runtime 增加交付面。其余交互回路（preview/review、局部重跑、人工验收）仍推迟。

前置条件：A4 viewer（LLM 反馈回路）、A5 提案机制（结构化报错）已就绪；LLM planner 模型名前缀 bug 修复排在近期主线首位（当前 401 为中转站 key 失效，见 Maintenance）。

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

- [ ] 修复 LLM planner API 配置（`.env` key 当前 401；Skill / LLM planner 生效前提）。当前无可用测试 key，暂搁置；401 归因为中转站 key 失效（2026-09-07 定性）。模型名格式 bug（`openai:` 前缀被原样发上 API，key 有效也失败）已修复：构造前剥前缀、兼容两种写法、README/config 对齐（2026-09-12）。

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
- [x] 调查当前 pytest warnings（2026-09-06）：4 条 RuntimeWarning（mock async edge-tts 的 `Communicate.save` coroutine 未 await）已修——`tests/test_edge_tts.py` 的 `asyncio.run` 替身现在关闭收到的 coroutine，`test_custom_speed_rate_string` 改为 patch `Communicate` 直接断言 rate 字符串。剩 2 条第三方 deprecation 修不了（修复在上游）：cloup `_util.py` 读了已废弃的 `click.__version__`（随 manim→click 引入，等 cloup 发版改用 importlib.metadata）；pydub `utils.py` 导入 `audioop`（Python 3.13 移除，等 pydub 上游跟进，当前 3.11 下不影响渲染链路）。测试数量只增不减，生产行为零变化。
- [x] 补测试：音频按 `segment_id` 绑定，不依赖 segment 列表顺序。
- [x] 补测试：render 成功但未生成新 `timeline.json` 时 hard fail，不复用旧 timeline。
- [x] 删除或重写旧 flat fallback 测试。
- [x] 删除或重写依赖 `ShotPlan.target_duration` 的测试。
- [x] 重写 marker-as-segment 的 renderer 测试为 marker-as-shot-cue。
- [x] 补测试：失败 run 不会让旧 `result.json` 被误认为当前 run 产物（并入 A4，run 目录制落地）。
- [ ] 已知边界（不修，保持行为逐帧不变）：合成器 loudnorm 需要 >=3s 音频才开始输出，更短的纯静音 run 会在 assembler 报 NaN 编码错误——真实 run 远超该下限；如需支持超短静音片再单独评估。
- [x] 补测试：非 0 起点 image shot 的 FFmpeg overlay / Ken Burns timing 正确（并入 A1）。
