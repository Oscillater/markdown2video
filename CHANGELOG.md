# CHANGELOG

已完成工作的历史记录。项目已结束功能开发，当前能力、限制和运行方式以 `README.md` 为准。

## 收尾修复（未发布）

本轮只修复已有行为，不增加 provider、组件、命令或 Agent harness。

- LLM Planner 保留原文镜头顺序：仅合并相邻同模板 Shot，允许 A/B/A 场景访问；explicit 段在原位置拆分。拒绝倒序/空镜头并走既有规则回退，移除提示词中不可执行的 stock_video 选项。
- Markdown 解析保留末尾无正文的小节标题，新计划使用当前 v2 版本。
- Manim 配音直接消费音频账本，不再用 manim-voiceover 重新量时长；动画之后只等剩余语音，不重复等待完整时长。
- Edge TTS 修正减速百分比；拒绝无效语速和音频时长，探测失败不再伪造 1 秒。WAV 请求做真实转换，兼容修复旧的 MP3 误命名缓存，下载失败不留下半截缓存。
- FFmpeg 合成对短于 3 秒的片段跳过 loudnorm，避免短静音 NaN；显式 gain（含 0）在有/无底片音轨时均生效。
- 各 ToolConfig 实例独立复制 provider 优先级列表；零语速不再被 Pipeline 静默替换为默认值。
- README 区分已实现能力、不提供的能力、信任边界与测试范围；移除 TODO / DECISIONS 规划文档，不再维护后续路线图。

## 2026-09-26

黄金帧与零散测试产物移出仓库；历史重写后修正 TODO 的 commit 引用。

## 2026-09-14 成片质量冲刺 P0/P1 收官

`math_canvas` 六轮读片迭代到 1.5.0。1.1.0 做动点，角度由累积活跃时间驱动，切走冻结、回场续转；1.1.1 否决「波和点各转各的」，改成波是点的高度投影，角速度由 cue 表推导为正弦锚点窗口结束恰好转完第一整圈，波头与动点严格同高；1.2.0 定调图层编排归 plan 作者不落代码，`visual_params.layers` 随组件场透传，组件不猜，header 段可进组件场作预热窗口，z-order 对调使 header 恒在组件之上，余弦改半径三角构造；1.3.0 章节化角度，动点一章转一圈、θ 分段线性、波只在自己章节内描出，章边界即切镜点且动点恰回最右，跨 shot 动画连续无跳变；1.4.0 聚焦降杂，历史波层降暗到 0.3，去掉垂足圆点装饰；1.5.0 余弦改竖排构造，波头横偏移等同动点横偏移、连接虚线垂直，零心理旋转，与正弦章形成「余弦是正弦转 90°」的字面对称。

`step_list` 升 1.0.2：行距改按换行行数动态累计，固定行距装不下两行文本会错位。

文字层改版 A/B/C，仅 Remotion 后端，manim 记为已记录差异。A 标题退场，title payload 携带 `end`（等于第一个正文镜头开始），标题只在片头出现一次；B 正文去重，朗读段不再由引擎画正文，字幕是文字唯一载体，静默段正文保留；C 章节牌，section header 升级为 accent 竖条加半透明底板，窗口改从 timeline text facts 取，开放到下一个 header。

对标片拆解：3b1b Chapter 3 的七段式结构和镜头语言清单，组件候选清单归档到 `docs/competitive-research.md`。

读片体检首例（coding agent 抽帧 12 帧，`trig_circle_kf`）：4 个 bug 级 + 2 个短板，结论是具体策略/实现问题而非路线问题。读片回路定为 coding agent 抽帧承担，VLM 读片助手取消立项。

## 2026-09-13 P0 知识区格式

代码生图 tool `GenImageTool`（`provider=procedural`，`visual_type=gen_image`）：PIL 确定性绘制四种母题（orbit/layers/waves/blocks），prompt 哈希作种子，跨运行逐字节一致，图内不渲染文字，generator 版本号进 cache_key。

烧录字幕：timeline text cue 转 ASS 走 libass，装配器尾部叠加，字幕永不被图片遮挡。白名单 content/appendix；只上真被朗读的段；libass 对无空格中文长句不断行直接裁边，所以构建期按像素宽度手动折行、行首避标点；`--subtitles` 默认关。

BGM 接线。BGM 资产本身也走代码产，`evals/assets/make_bgm.py` 合成 20s 无缝循环，颤音周期整除循环时长保证相位连续。

验收片 `trig_circle_kf.mp4`，65.7s，解说加程序化插画加字幕加 BGM 四样齐。过程中修了两个：`gen_image` 返回相对路径被 `--plan` 场景的装配器静默丢弃，改返回绝对路径并给装配器加 cwd 回退，缺图从静默丢弃改显式告警；插图 Ken Burns 持续抖动，成因两层——`zoompan` 按输入像素格点取整，且超采样后仍周期性顿挫，修法是超采样 4x 后保持超采样尺寸做 zoompan 再用 lanczos 缩回，像素级验证连续 40 帧 0 对相同、帧差均匀 0.29~0.50。

A8.1 场景画布落地。`register_component(mount="shot"|"scene")` 由注册表声明；按场挂的组件拿到整场镜头时间线；状态累积是纯函数推导，不靠运行时记忆；`plan.scenes` 允许同一 scene id 复现表示「回到这场」。试点组件 `math_canvas@1.0.0` 入库，showcase 首片 65.7s，画布三次访问的累积叙事成立。

## 2026-09-12 A8 组件管线、口播 skill、bundle 导出

A8 组件注册：注册表加显式模块加载（env `MD2VIDEO_COMPONENTS`）；`ScenePlan.component` 字段与裁判；调度器产 payload，Node wrapper 按 shot 窗口挂载；验收入口 `python -m md2video.check_component`——禁用 API 静态扫描、staged 安装、fixture 真渲染两遍、timeline 逐字节加 framemd5 逐帧一致、黄金帧，全过才提交安装。首批三组件入库：`step_list@1.0.0`、`code_display@1.0.0`、`terminal@1.0.0`。

B2 口播 skill v1（`skills/voiceover/SKILL.md`）：结构模板、切镜规则、组件货架、命令用法、读 viewer 迭代。首片 `git_internals.md` 出片 71s 零 warning。踩的契约坑写回 skill——要朗读的 segment 必须显式带 `audio_request`，缺了就是静默段，管线不读也不警告，首跑曾全片无声。

A9.1 bundle 导出（`--bundle`）：`subtitles.srt`、`timeline.edl`（CMX3600）、按 shot 边界重编码切片、`assets/`。必剪与 Clipchamp 各建工程导入三类素材实机验收通过。过程抓到一个真 bug：edge-tts 产物名 `.wav` 实为 mp3，必剪按扩展名静默拒收，改成 `_copy_assets` 拷贝前按魔数识别真实容器再定扩展名。

LLM planner 模型名前缀 bug 修复，`openai:` 前缀此前被原样发上 API。

## 2026-09-08 CLI 全链路补验

真跑暴露并修复三个 mock 盖不住的集成 bug。一是 `remotion_tool` 子进程 cwd 切到 backend_dir 后相对路径错位，改成先 `resolve()` 再传 CLI；二是 `ffmpeg_assembler.ffprobe_resolution` 对 Remotion 容器多出的尾部空字段 `480x854x` 做 `int('')` 炸裂，改成只取前两段；三是调度器的 before/after 锚点 cue 挂上时间后从未 append 进 `markers_out`，时间闸门直接拒绝、图片和 BGM 条目为空。

另：`timeline.otio` 独立读回校验 19/19 通过；装官方 `otio-cmx3600-adapter` 把真文件转成 CMX 3600 EDL 成功。

## 2026-09-07 Track A 第二、三批

A4 Runtime Inspectability：run 目录制（run_id 是时间戳加短随机后缀，永不覆盖永不删除）和 `manifest_viewer.html` 单文件自包含检查页。

A5 Layout 提案机制：`ScenePlan.layout_regions` 直接提案、约束注册表（零特权 `register_constraint`）、结构化 `LayoutIssue`（code / region / expected / actual / suggestion，一次报全部）、子构图 region 化。

外部皮肤包文件加载（`MD2VIDEO_STYLE_PACK_FILE`）。

A6 混合引擎。前半是按 scene 多后端分发——分组切片、局部 timeline 前缀偏移合并、全局时间闸门重过、底片拼接；后半是 Remotion 真实第二后端——纯函数调度器 `remotion_schedule.py` 加 Node composition，能力词汇声明与降级，双跑 framemd5 逐帧一致。

A9 OTIO 导出：`timeline.json` 到 OpenTimelineIO 的纯函数 lowering，经适配器可达 EDL / FCPXML / AAF。

## 2026-09-06 Track A 首批

A1 时间不变量闸门（`timeline/invariants.py`）：shots 覆盖、按序、不重叠、cue 归属、朗读差值告警。

A2.5 渲染后端去硬编码，按 `ToolConfig.render_backend` 选择。

A2 与 B1 Style Pack：`ThemeTokens` schema、`ManimRealizer` 作为唯一换算点、motif kind 注册表、reference pack `ink_night`，像素逐帧不变验收通过。

A3 Plan Schema v2：plan 不含时间，`SegmentPlan.target_duration` 移除，一次切换完成（`manifest/migration.py`）。

修复渲染分辨率 bug：`-ql` 质量旗标覆盖 `manim.cfg` 的竖屏声明导致横屏输出。

## 2026-09-05

设计共识定稿：四本账、四道闸门、双 track 路线。定义写入 `docs/architecture.md`。

## Phase 1–6

Phase 1–4 基础架构到现有工具重构；Phase 5 Runtime artifact 分层加 Manifest-first execution；Phase 5.5 Runtime Layout Template；Phase 6 Renderer Closure，渲染契约与 layout consumption 落地，像素级 smoke 验证通过。
