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
  -> Plan IR: Scene / Shot / layout intent（不含时间）
  -> Scheduled Render IR: renderer 内部执行单元和 cue
  -> Runtime Facts: execution-assets.json + timeline.json
  -> Delivery: result.json + MP4
```

- Parser 只把 Markdown 变成内容结构，不决定最终视觉。
- Planner 把内容结构 lower 成 scene/shot/layout/素材意图。
- Tool 只产生素材事实，例如音频文件、图片文件和它们的 duration/尺寸。
- Renderer 执行计划并产出真实时间线。
- Assembler 不重新规划，只按 timeline 把素材对齐到最终视频。

## 总体模型

整个系统只有三类角色：**提案者**（用户 / LLM / 内置模板，平等无特权）、**裁判**（约束校验与解析）、**执行者**（确定性 tools）。四本账规定每个决定只住一个地方；四道闸门保证执行层交付合法。

### 四本账

- `plan`：内容与编排意图。不含时间，不含风格取值。
- `pack`（设计包）：风格与节奏的单一事实源。用户直接改包（Hugo/Hexo 模板模型），不存在多来源自动合并。
- 账本（`execution-assets.json` + `timeline.json`）：事实。素材、时长、时间线，谁产出谁发现，只进账本、不回流 plan。
- 裁决：时长等歧义只允许唯一纯函数裁决（音频事实 > 显式 hold cue > pack 节奏默认）。

### 四道闸门

执行层的约束体系，也是未来任何新渲染后端的验收标准：

1. layout 约束：几何合法（安全区、不重叠、最小尺寸）。
2. style 校验：token 合法。
3. 时间不变量：时序合法（shots 覆盖、有序、不重叠、cue 归属）。
4. 渲染契约：交付合法（字段、文件存在；分辨率由 manim.cfg 声明，禁止质量旗标覆盖）。

### 三条贯穿机制

- 降级链：preferred_provider > 配置优先级表 > 降级并记 warning；显式本地素材缺失 fail fast。
- 缓存合同：工具输出携带 cache_key，内容寻址缓存。
- warnings 全程收集：降级、缺失、时长差异进 result.json，供检查页与未来 harness 展示。

## 覆盖地图

每条设计原则自带「已有实现（证据）」与「待补」，防止文档把未实现写成已完成。

| 原则 | 已有实现（证据） | 待补 |
|---|---|---|
| 时间解耦：时长是事实，谁产出谁发现 | TTS 先行、时长进账本；渲染器内音频按 segment_id 绑定播放；音乐循环流裁剪到已知 shot 区间；timeline 是唯一时间事实；时间不变量闸门（`timeline/invariants.py`：覆盖/按序/不重叠/cue 归属/朗读差值告警）；plan 已去 target_duration（v2 迁移）；素材 duration 合同（VisualAsset.duration）；时长估算器（`timeline/estimate.py`，仅容错决策与展示）；估算消费方（A4 viewer 预计 vs 实际） | hold cue 入口（概念位已留） |
| 提案→裁判→交付（layout） | ComputedLayout 属性校验；注册表重复注册 fail-fast；mapping.py 双消费端共享；regions 直接提案入口（`ScenePlan.layout_regions`，`layout/resolve.py`，与模板同一裁决）；结构化报错（`LayoutIssue` + `LayoutValidationError`，一次报全部，含数值与建议）；约束注册表（`layout/constraints.py`，零特权 `register_constraint`，env `MD2VIDEO_LAYOUT_CONSTRAINTS` 显式加载外部约束模块）；子构图 region 化（center_title_body 的 `section_stack` 子 region） | —— |
| 风格声明化（style/pack） | ThemeTokens schema（`style/schema.py`）；ManimRealizer 唯一换算点；motif kind 注册表（orbit_dots）；reference pack `ink_night`（像素逐帧不变验收通过）；外部文件包加载（env `MD2VIDEO_STYLE_PACK_FILE`，`get_pack` 路径惰性加载一次、坏文件 fail fast、未知名降级 + warning） | —— |
| 工具合同化 | Tool Protocol + 注册表 + cache_key 缓存；降级链；local 免 key / pexels 可选 key；渲染后端按 `ToolConfig.render_backend` 选择（A2.5）；VisualAsset.duration 合同落地；按 scene 多后端分发（A6：`ScenePlan.render_backend` + `core/multi_backend.py` 切片/合并/拼接/全局闸门）；Remotion 真实第二后端（A6 后半：`tools/render/remotion_tool.py` 同一渲染契约 + `remotion_schedule.py` 纯函数调度器 + Node composition，能力词汇声明、词汇外降级 + warning） | —— |
| 内容词汇表 | 标题/段落/附录；marker/媒体标记 lowering 机制已在 | 列表/强调/引用（A7 挂起：md 入口下结构被拍平，agent 走 `--plan` 可绕开；重启时表现优先走组件路线评估） |
| plan 收敛 | scene 级 visual/layout 决策已在；SegmentPlan 副本字段已收拢（v2 去 denormalize） | —— |
| 可检查性（A4） | run 目录制（`inspect/runs.py`：新建+命名区分，永不覆盖/删除）；`FinalResultManifest.run_id/status`；静态检查页（`inspect/viewer.py`，黄金快照测试） | 未来 harness 直接读取 run 目录（不要求编辑/审批 UI） |
| 演进纪律 | segment_ids→shot 迁移 validator；破坏性变更一次切换先例；plan 去时间已按同模式执行（`manifest/migration.py` + 一次切换） | —— |
| 质量策略 | 纯函数 helper 层（renderer 可无 manim 测试）；mock 外部服务；env-gated 像素 smoke | —— |
| 组件注册（A8） | 零特权注册先例已在：motif kind 注册表（`style/motifs.py`）+ 约束注册表（`layout/constraints.py` 的 `register_constraint`）；代码只经显式模块加载、pack JSON 永不执行（A5 模式） | 表现组件契约：输入 = 文字 + 可见窗口 + 画布，输出 = 自由画面（自带视觉，不消费 pack token）；两条底线 = 不改时间事实 + 确定性渲染；验收入口 `check-component`（时间闸门 + 双跑逐帧一致 + 黄金帧存档，不设人工审核；组件场景的 layout 合法性由上架验收承担，运行时机器检查只覆盖引擎渲染画面）；plan 引用 `id@version`，内容哈希进 result 供审计 |

## 核心数据模型

- `Segment`：内容原子，通常是一句话或一个标题。Markdown marker 可以作为 source event 被识别，但进入 renderer contract 前应 lower 到 shot cue/metadata。
- `Shot`：最小连续视觉执行单元。一个 shot 包含一组有序 segment_ids 和 cue，并保持一段连续视觉状态。需要画面连续的内容（如一段数学演算）应整体放进同一个 shot，由组件在 shot 窗口内连续渲染。
- `Scene`：视觉策略组。一个 scene 可以包含多个共享素材策略、layout/template 和风格决策的 shot。分工：**组件针对 shot**——注册组件逐 shot 窗口接管正文画面；**scene 满足风格**——scene 是风格化单位，经 `ScenePlan.component`（`id@version`）声明本组 shot 用哪个组件，风格注册一次、处处引用。

Manifest 是 Planner、Tool、Renderer、Assembler 之间唯一的数据流。工具之间不应该直接通信。

## Runtime Contract

Runtime contract 定义 planner、tools、renderer 和 assembler 对 Manifest 与 runtime artifacts 的共同理解。简言之：`plan.segments` 是内容字典，`scene.shots[].segment_ids` 决定执行顺序，静默段时长由 pack 节奏与音频事实决定（plan 不含时间），renderer 输出的 `timeline.json` 是最终时间事实。

- `Segment` 是内容原子，不自动等于显示单元、朗读单元和时间单元三合一。一个 segment 可以产生 audio cue、visual cue 或 animation cue，但这些 cue 不必拥有相同生命周期。
- plan 不含时间（v2）：segment 不携带任何时长字段。静默段的时长由渲染器按 pack 节奏发现；shot duration 由内部 segment/cue 的实际执行结果聚合得出。
- `Shot` 是最小连续视觉单元，持有一组有序 `segment_ids`，并携带 marker / media / visual event cue metadata。
- `Scene` 是共享视觉策略、素材策略和 layout/template 决策的 shot 组。scene 可以持有 `visual_type`、`layout_type`、`layout_params` 和 `component`（注册组件引用，逐 shot 渲染），但不决定 segment 顺序。
- Renderer 必须按 `plan.scenes -> scene.shots -> shot.segment_ids` 遍历。`PlanManifest.segments` 只作为按 id 查找的内容字典，不决定渲染顺序。
- 显示和朗读是分开的。`audio_request` 表示文本是否需要朗读；visual/layout/template 逻辑决定画面显示什么、显示多久。
- `section_context` 只是 metadata，用来记录 segment 属于哪个 section。它不是并行显示文本，也不是并行朗读内容。若需要持续显示 section title，应由 layout/render template 显式表达，而不是从 `section_context` 推断。
- Markdown marker 可以先被 parser 识别为事件，但进入 renderer/scheduling 层前必须 lowering 成 shot 上的 marker cue/metadata。marker 不作为正文 segment 渲染、不朗读、不消费 duration。
- duration 分配不是全局固定规则，而是由 segment type 加设计包节奏共同决定。有声 content 通常跟随 audio duration；静默可见 content/header 使用 pack 静默节奏；marker 默认是 0 duration 的时间点事件；animation duration 必须计入 segment/shot 预算。
- `timeline.json` 是 renderer 输出的最终时间事实。`shots` 是主时间轴，必须由 renderer 显式写出 `start/end`；`text` 是可见文本 cue；`markers` 是时间点事件 cue。
- assembler 以 `timeline.json` 为时间源，但消费前必须校验它覆盖当前 plan 的 shots、可见文本 cue 和 marker cue。缺失、过期或不一致的 timeline 必须 fail fast。
- 烧录字幕选段三条规则（同层同性质）：①白名单 content/appendix（标题与 section header 有自己的屏上位置）；②只上真被朗读的段（音频资产事实优先，缺位回退 plan `audio_request`）；③**文字载体归组件时，字幕让位**——组件场里被朗读且被组件 `displayed_texts(payload)` 声明画上屏的段跳过字幕（组件文字即该段载体；与文字层 B 的分工：引擎画正文时字幕让位是同一条原则的装配层延伸）。组件未注册/未安装/未声明一律保留字幕（宁重勿丢：降级路径下引擎默认渲染的朗读段不画正文，字幕是唯一文字载体）。timeline text facts 保留不删（组件显示它也是可见事实），只在装配消费时跳过；bundle SRT 是给剪辑软件的可编辑全量轨，不做此跳过。

## Runtime Artifacts

每次 run 在 `artifacts/runs/<run_id>/` 下产生独立目录（run_id = 时间戳 +
短随机后缀，可排序、全局唯一），本次全部产物都落在其中：四类账本、
manim 渲染目录、per-shot visual、检查页。**旧 run 永不覆盖、永不删除**；
归属与失效判断只靠 run_id 与命名（产物只增不删）。输出 MP4 路径仍由
用户指定。四类账本 artifact：

- `plan.json`：计划和目标约束，描述 segments、scenes、shots、visual intent 和 layout intent；不含时间。
- `execution-assets.json`：素材事实，记录 TTS 音频路径/时长、图片路径/尺寸、provider 和 cache key。
- `timeline.json`：renderer 实际输出的时间事实；shots/text 使用 `start/end`，marker cue 使用 `time`。
- `result.json`：最终交付摘要，只在 assemble 完成后写出，记录 output MP4、used assets、warnings 和 artifact index；带 `run_id` 与 `status`（completed/failed）。失败 run 在自己的 run 目录写 failed result，旧 run 的 result 永不被触碰。

`result.json` 不应该承担中间执行状态；renderer 和 assembler 应该显式消费 plan、execution assets 和 timeline。

另有 `manifest_viewer.html`：一次 run 的紧凑静态检查页（单文件自包含，
无外部网络资源），汇总 plan 意图、素材事实、时间事实、交付摘要、
warnings 与预计 vs 实际时长（消费 `timeline/estimate.py` 估算 + timeline
末 shot end），供人与未来 harness 不读原始 JSON 看懂一次运行。

另有 `timeline.otio`：同一 timeline 事实面向剪辑生态（Resolve / FCP /
Premiere，经 OTIO 的 EDL/FCPXML/AAF 适配器）的 OpenTimelineIO 交换
序列化（A9）。纯函数 lowering（`timeline/otio_export.py`）：shots →
Video track Clip，marker cue → 所属 shot Clip 上的 Marker，text cue →
Clip metadata 事实；opentimelineio 缺失或导出失败时降级为 warning，
不阻断 MP4 交付。

面向消费级剪辑软件另有可选的混剪素材包（`--bundle`，
`timeline/bundle_export.py`）：按 shot 边界重编码切片、口播字幕 SRT
（挂屏标题类排除）、CMX3600 EDL、原始图片/BGM/配音——音频按内容
魔数纠正扩展名（edge-tts 可能名 .wav 实为 mp3，按扩展名验格式的
消费级软件会静默拒收）。文本产物逐字节确定；子步失败折进 warnings。
消费级软件只到「素材池」层，时间线组装人工按序拖切片（剪映草稿注入
为未来候选项）；专业 NLE 走 EDL/OTIO。

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

工具的合同义务：

- 产出会占用时间轴的素材，输出必须携带 duration（静态素材为 0）；输出必须携带 cache_key。
- 时长归属唯一：音频=TTS、shot=渲染器、视频素材=素材工具 probe；其他模块不许断言时长。

渲染后端是特殊的 tool：消费 plan 与 execution-assets，输出视频与同构 timeline。引擎与设计包正交（见 Style 与 Pack）；引擎声明自己支持的能力名（动效意图、母题 kind），不认识的槽位优雅降级 + warning。按 scene 混合多后端时：`ScenePlan.render_backend` 为空的 scene 用 `ToolConfig.render_backend`；相邻同后端 scene 组成极大组，每组切片 plan 独立渲染（各后端从 t=0 渲自己的切片，组边界即引擎切换，渲染器内部跨 shot 状态清零），管线做局部 timeline 前缀偏移合并后对完整 plan 重过全局时间闸门，再把组视频拼接成底片交给 assembler（成片规格与单后端一致）。要求的后端未注册时开渲前 fail fast。

当前有两个渲染后端：`manim`（默认）与 `remotion`（A6 后半）。Remotion 侧的时间不是渲染中发现而是**渲染前推导**：纯函数调度器（`remotion_schedule.py`）从音频事实 + pack 节奏得出逐段可见窗口，Node composition 逐帧执行同一份调度，成片时长经 ffprobe 与调度对账；这保持「timeline 是唯一时间事实、时间由执行发现」的合同（发现者从 manim-voiceover 换成调度器消费的音频事实账本）。

## Visual 与 Layout

项目拆开三个决定：

- `visual_type`：用什么素材或工具，例如 text、stock image、local image、video；Manim 是 `render/manim` backend，不是 visual provider。
- `layout_type` / `layout_regions`：这些素材、文字、字幕放在屏幕哪里。
- `theme`：长什么样、怎么动（见下一节 Style 与 Pack）。

**Layout 是约束机制，不是模板库。**提案者（内置模板 / `ScenePlan.layout_regions` 直接提案 / 用户配置）地位平等，产出候选 region 集合，由同一套属性校验裁决（`layout/constraints.py` 的约束注册表：安全区包含、内容区不重叠、最小尺寸）；设计包与用户可经零特权 `register_constraint(fn)` 注册追加约束。通过则 `ComputedLayout` 交付给 tools；拒绝则返回结构化错误 `LayoutValidationError`（每条 `LayoutIssue` 带哪个 region、期望/实际数值、怎么改，一次报全部问题），供 LLM 自我修正。提案里名为 `image` 的 region 是视觉槽位（可全屏出血、允许文字叠上），豁免安全区与重叠检查，与内置模板对 image region 的用法一致。

外部约束模块通过 env `MD2VIDEO_LAYOUT_CONSTRAINTS`（逗号分隔 Python 模块路径）显式加载：pipeline 启动时导入并执行其注册，导入失败 fail fast。pack 的 JSON 文件永远纯数据、绝不被自动执行；要自定义规则的包作者随包附一段独立注册模块，由用户显式启用。

子构图归 layout：center_title_body 的 section header 左列堆叠边界由模板子 region `section_stack` 表达（嵌套子 region，不参加内容区重叠检查），渲染器只负责把内容装进 region；渲染器的自由度收敛为 region 内的动效（动效语义归 style）。

当前内置提案器（`center_title_body` / `full_bleed_image_caption_bottom` / `image_top_text_bottom`）继续作为默认值与示例存在。Layout 参数由模板自己的 Pydantic schema 校验；runtime 在执行 TTS、渲染和合成前先完成 layout 解析与约束校验。

layout 冻结：不再加模板、不再演进，新表现力一律走注册组件；运行时不新增 layout/风格检查，组件上架验收（check-component）是唯一关卡。

Manim 和 FFmpeg 通过共享的坐标换算层（`layout/mapping.py`）消费同一套 layout，两者对模板的理解来自同一组函数：

- Renderer 用 `shot_layout_context` 把 shot 的模板解析成单位空间的 region 摆放：正文/字幕堆叠落在 body/text/caption region，标题卡片落在 title region，文本按 region 宽度约束缩放。
- Assembler 用 scene layout 的 `image` region 摆放 per-shot visual：Ken Burns cover 整个 region，静态 overlay contain 进 region；无 layout 契约的条目（如 Markdown marker 图片）保持 legacy 定位，因为 marker 时间区间可以跨 shot。
- `timeline.json` 的 shots 条目记录 `layout_type`，供检查和未来 harness 使用。

## Style 与 Pack

风格是第四个声明维度，与引擎正交：

- **pack 是纯数据宣言**：`ThemeTokens` = palette（底/字/次级/强调色）+ typography（字族 + 角色字号，归一化单位）+ motion（意图级动效 + 静默段节奏）+ motif（母题槽位：可换、可无、可自定义）。
- **引擎自带 Realizer（翻译官）**：token → 引擎原生参数的唯一换算点。ManimRealizer 翻成 font/font_size/color/动画选择；Remotion 侧由 `remotion_schedule.py` 的 style payload 翻成 CSS 值（像素字号/颜色/意图名），Node composition 实现能力原语（typewriter/fade/appear、instant/fade、orbit_dots 母题）。宣言只有一份，翻译官每个引擎一个。
- **能力按名字引用**：pack 写 `appear: typewriter`、`motif: orbit_dots` 这类名字；引擎声明自己支持哪些名字，不认识的槽位优雅降级 + warning。
- **用户直接改包**（Hugo/Hexo 模板模型）：DIY 就是编辑包内容，无多来源合并问题。仓库自带一个 reference pack（现有 house style 抽取），结构上与社区包无特权差别。外部包文件经 env `MD2VIDEO_STYLE_PACK_FILE`（指向 ThemeTokens JSON）加载：在 `get_pack` 解析路径上惰性加载一次（幂等缓存，管线与渲染子进程两侧一致）；文件解析/校验失败、缺文件、与已注册包重名都 fail fast（用户显式指定的包坏了必须报错），选择仍走 `MD2VIDEO_STYLE_PACK` 名字、未知名降级 + warning。

关键性质：`引擎代码量 = N 引擎 × (1 个 Realizer + K 个能力原语)`，不随模板和包的数量增长。加新 layout 模板或新 style 包都是纯数据注册，引擎零代码；只有引入全新能力（新母题 kind、新动效意图）时，想支持的引擎各补一个实现。

边界：合成器 v0 不消费 style（底色字体烧在底片里）；Ken Burns 参数、音乐音量是 pipeline 配置，不进 pack。

与表现组件（A8）的分界：换个 pack 跟着变的归 pack（全片气质：palette / 字号 / 节奏 / 动效意图）；不变的是组件（一类内容的演法，如终端展示、代码高亮）。组件场景的画面由组件自带视觉负责，不消费 pack token；pack 的动效意图只作用于引擎默认渲染的画面。

选择分工：pack 是全片级配置决定（env 选择，默认包），不进 planner 的场景级选择面；planner（skill 指导下的 agent）按内容挑的是组件——场景级，写进 `ScenePlan.component`。第二套气质出现时再考虑把 pack 写进 plan 头部，使 plan 自描述。

## 渲染分辨率

画面尺寸由 `md2video/tools/render/manim.cfg` 声明（竖屏 480x854 @30fps）。渲染 backend 不传 Manim 质量旗标：质量预设（如 `-ql`）会把分辨率覆盖成 16:9 横屏，破坏 layout 归一化坐标的前提。

## 时长

目标契约：**plan 不含时间**。时间住在四个地方，plan 不在其中：

- 音频时长：TTS 工具发现，进 execution-assets（事实）。
- shot 区间：渲染器发现，写 timeline（事实）。
- 静默段节奏：来自设计包的 motion token（"这一类内容停几秒"是风格问题）。
- 显式停顿：hold cue（创作意图的事件表达，未来入口）。

判断标准：换个设计包它变不变？变 → 归 pack；不变且已发生 → 归事实；是创作决定 → 归 cue。

`SegmentPlan.target_duration` 已在 plan schema v2 迁移中移除（`manifest/migration.py`，一次切换）：有声段由音频事实驱动，静默段由设计包 motion token（`silent` 节奏）驱动。

裁决唯一：段时长 = 音频事实 > hold cue > pack 默认，全仓库只允许一处裁决函数。渲染前估算只服务容错决策与展示（配乐选择、总长告警），永不用于组合。

- 有 `audio_request` 的 segment 由音频/voiceover 决定实际朗读时长，视觉显示可以跟随或覆盖，但不能截断语音。
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
| plan v1→v2 迁移（去时间、去副本字段） | `manifest/migration.py` | `test_manifest_migration.py` |
| 规划（scenes/shots/cues，rule + llm） | `core/planner/rule_planner.py`、`core/planner/llm_planner.py` | `test_rule_planner.py`、`test_llm_planner.py` |
| Layout（模板、注册表、共享坐标换算） | `layout/schema.py`、`layout/templates.py`、`layout/registry.py`、`layout/mapping.py` | `test_layout.py`、`test_layout_mapping.py` |
| Layout 裁决（约束注册表、结构化 LayoutIssue、提案解析） | `layout/constraints.py`、`layout/resolve.py` | `test_layout_constraints.py`、`test_layout_proposal.py` |
| 工具（契约、注册、缓存、TTS/图片/渲染实现） | `tools/protocol.py`、`tools/registry.py`、`tools/cache.py`、`tools/tts/`、`tools/image/`、`tools/render/manim_tool.py` | `test_tool_protocol.py`、`test_tool_registry.py`、`test_tool_cache.py`、`test_edge_tts.py`、`test_pexels_image_tool.py`、`test_local_image_tool.py`、`test_manim_tool.py` |
| 编排（五步流水线、fail-fast、降级分发） | `core/pipeline.py` | `test_dispatch.py`、`test_pipeline_artifacts.py` |
| 多后端分发（分组切片、timeline 合并、底片拼接、全局闸门） | `core/multi_backend.py` | `test_multi_backend.py`（混合 manim/fake 验收为 env-gated smoke） |
| 渲染（shot 级渲染、timeline 事实） | `tools/render/manim_renderer_inputs.py`（纯 helper）、`tools/render/manim_renderer.py`、`tools/render/timeline_builder.py`、`tools/render/manifest_loader.py`、`tools/render/cached_voice.py` | `test_manim_renderer_inputs.py`、`test_renderer_timeline_state.py`、`test_cached_voice.py` |
| Remotion 后端（第二渲染后端：调度器 + 契约工具 + Node composition） | `tools/render/remotion_schedule.py`、`tools/render/remotion_tool.py`、`tools/render/remotion_backend/`（Node 工程） | `test_remotion_backend.py`、`test_remotion_smoke.py`（env-gated 真渲染） |
| 时间不变量闸门（shots 覆盖/按序/不重叠、cue 归属、朗读差值告警） | `timeline/invariants.py` | `test_timeline_invariants.py` |
| OTIO 交付导出（timeline 事实的剪辑生态交换 serialization） | `timeline/otio_export.py` | `test_otio_export.py` |
| 混剪素材包（消费级剪辑软件的素材/字幕/EDL 交付，`--bundle`） | `timeline/bundle_export.py` | `test_bundle_export.py` |
| 时长估算（音频事实 + pack 节奏 + 转场开销常数，仅容错/展示） | `timeline/estimate.py` | `test_timeline_estimate.py` |
| Run 目录制（run_id、独立 run 目录、永不覆盖） | `inspect/runs.py` | `test_run_dirs.py` |
| 检查页（单文件自包含 viewer、预计 vs 实际时长） | `inspect/viewer.py` | `test_manifest_viewer.py`（含黄金快照） |
| Style（ThemeTokens、pack 注册、ManimRealizer、母题注册表） | `style/schema.py`、`style/packs.py`、`style/manim_realizer.py`、`style/motifs.py` | `test_style_schema.py`、`test_style_manim_realizer.py`、`test_style_motifs.py`、`test_style_pack_file.py` |
| 合成（按时间事实混音、region 叠图） | `assembler/ffmpeg_assembler.py` | `test_ffmpeg_extractor.py`、`test_ken_burns.py` |
| 配置（常量、.env 加载） | `config.py` | 随各层测试覆盖 |
| 像素 smoke（端到端落位验证，默认跳过） | `tests/test_render_smoke.py` | `MD2VIDEO_RENDER_SMOKE=1` 触发 |
