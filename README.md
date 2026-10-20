# markdown2video

**本地可复现、插件化可扩展的 Manifest 驱动视频编译器** — 将 Markdown 讲稿或结构化 `PlanManifest` 编译为带 TTS 配音、配图、BGM、字幕与预置组件动画的 MP4 视频。

`markdown2video` 采用「**内容与时间分离**」的编译管线设计：人或外部 Agent 负责决定讲什么、怎么编排（产出 Markdown 或 `PlanManifest`），Python 管线负责合成配音、准备素材、调用 Manim / Remotion 渲染画面、对齐真实时间线并用 FFmpeg 合成交付产物。默认输出 480 × 854、30 fps 竖屏视频。

同时，它被设计为一个**面向开发者与 Agent 的可扩展底座**：基于统一的 `PlanManifest` 契约，你可以自由扩展 **Tool 插件**（接入新的素材源、TTS 或渲染后端）、注册带确定性验收的 **TSX 表现组件**（扩展新的画面演法与可视化动效）、定制 **设计包（ThemeTokens）与布局约束**，或编写新的 **Agent Skill** 来定义全新的讲解风格——所有扩展均可无缝接入同一套校验与合成管线，无需侵入核心代码。

> **项目状态**：本项目已归档开发记录并开源，背后的设计演进与复盘详见 [blog](https://oscillater.github.io/tech-notes/%E7%9C%BC%E5%89%8D%E6%9C%89%E6%99%AF%E9%81%93%E4%B8%8D%E5%BE%97%EF%BC%9Amarkdown2video+%E7%9A%84%E5%A4%B1%E8%B4%A5) 与 [CHANGELOG.md](CHANGELOG.md)。

---

## 核心特性

- **四层插件化扩展架构**：围绕 `PlanManifest` 契约解耦扩展边界——支持注册自定义 **Python Tool Provider**（图片/素材/渲染后端并配置降级链）、开发带静态扫描与黄金帧验收的 **React/TSX 表现组件**、挂载外部 **设计包（ThemeTokens）/ 布局约束**，以及横向扩展 **Agent 风格 Skill**。
- **三种输入工作流**：支持约定格式的 Markdown 直出、精确控制分镜与组件的 `PlanManifest` JSON 驱动，以及通过内置 Agent Skills 由宿主 Agent 编排成片。
- **内容与时间严格分离**：Plan 只声明内容与视觉意图，不写死秒数；真实时长由 TTS 音频实测决定，再由渲染后端生成并通过不变量校验的 `timeline.json` 驱动合成。
- **双渲染后端与混合编排**：内置 **Manim**（偏文字排版）与 **Remotion**（Node/React，支持表现组件动画），支持按 Scene 指定后端并自动合并相邻同后端场景，也可接入自定义渲染后端。
- **确定性表现组件库**：提供经固定夹具与黄金帧验收的 TSX 组件（步骤列表、代码着色面板、终端窗口、单位圆与正余弦数学画布），按语义化版本引用，杜绝运行期让大模型即兴手写动画代码导致的崩坏。
- **可审计的运行产物**：每次运行生成独立 `run_id` 目录，落盘 `plan.json`、`execution-assets.json`、`timeline.json`、`result.json` 与单文件可视化检查页 `manifest_viewer.html`，支持导出 ASS 烧录字幕、SRT、OTIO 时间线与剪辑素材包（Bundle）。
- **明确降级与缓存机制**：TTS 与图片工具自带 `cache_key` 复用；素材获取失败按配置链降级并完整记录 `warnings`，本地显式文件缺失或时间线违规直接报错阻断。

---

## 目录

- [快速开始](#快速开始)
- [环境与安装](#环境与安装)
- [使用指南](#使用指南)
  - [1. Markdown 脚本直转](#1-markdown-脚本直转)
  - [2. PlanManifest JSON 驱动](#2-planmanifest-json-驱动)
  - [3. 使用表现组件（Remotion）](#3-使用表现组件remotion)
  - [4. Agent Skills 编排](#4-agent-skills-编排)
  - [5. LLM Planner（可选）](#5-llm-planner可选)
- [CLI 与环境变量参考](#cli-与环境变量参考)
- [工作原理与管线架构](#工作原理与管线架构)
- [运行产物与质量检查](#运行产物与质量检查)
- [能力边界与已知限制](#能力边界与已知限制)
- [扩展开发](#扩展开发)
- [项目结构与测试](#项目结构与测试)
- [许可证与支持](#许可证与支持)

---

## 快速开始

### 1. 最小示例（Markdown 直出）

完成[环境与安装](#环境与安装)后，新建 `script.md`：

```markdown
# 从 Markdown 到视频
## 一个最小示例

### 准备脚本
把正文放在小节标题下面，就可以生成配音。

### 生成视频
默认使用规则规划器，不需要大模型 API Key。
```

运行默认管线（Manim 后端 + 规则规划器）：

```bash
uv run --all-extras python -m md2video script.md -o output.mp4
```

烧录口播字幕并导出可二次剪辑的素材包（含分段视频、SRT、EDL）：

```bash
uv run --all-extras python -m md2video script.md -o output.mp4 --subtitles --bundle
```

### 2. 切换 Remotion 后端或运行内置组件示例

使用 Remotion 渲染后端（推荐开启 `--subtitles`，因为 Remotion 默认通过烧录字幕呈现有声正文）：

```powershell
$env:MD2VIDEO_RENDER_BACKEND = "remotion"
uv run --all-extras python -m md2video script.md -o output.mp4 --subtitles
```

直接运行仓库自带的数学可视化组件示例（需先安装 Remotion 依赖）：

```bash
uv run --all-extras python -m md2video --plan evals/trig_circle.plan.json -o trig_circle.mp4 --subtitles
```

---

## 环境与安装

### 前置依赖

- **uv**：管理 Python 解释器、虚拟环境与锁文件（[安装指南](https://docs.astral.sh/uv/getting-started/installation/)）。
- **Python 3.11**：`.python-version` 默认指向 `3.11`（兼容 `>=3.11,<3.13`），可由 `uv` 自动下载。
- **FFmpeg 与 ffprobe**：需加入系统 `PATH`；使用 `--subtitles` 时需包含 `subtitles` 滤镜（`libass`）。
- **Manim 后端依赖**：Python 包由 `uv` 安装；部分操作系统需自行安装 Cairo / Pango 系统库。
- **Remotion 后端依赖（可选）**：需 Node.js 22+ 与 npm，并在 `md2video/tools/render/remotion_backend` 下执行 `npm ci`（首次渲染会自动准备 Headless 浏览器）。
- **中文字体**：默认设计包使用 `FZShuSong-Z01S`，字幕使用 `Microsoft YaHei`。若系统缺失对应字体，可能发生字体回退或排版偏差。
- **网络环境**：首次拉取依赖、下载无头浏览器以及合成未缓存的 Edge TTS 语音需联网（Edge TTS 无需 API Key）。

### 安装步骤

在仓库根目录同步全部依赖并验证 CLI：

```bash
uv sync --locked --all-extras
uv run --all-extras python -m md2video --help
```

如果使用 Remotion 后端或 TSX 表现组件，需安装前端依赖：

```bash
cd md2video/tools/render/remotion_backend && npm ci && cd ../../../..
```

也可以按需安装可选依赖组（每次 `uv sync` 以当前传入的 `--extra` 为准）：

| 安装命令 | 包含能力 |
|---|---|
| `uv sync --locked` | 核心管线（Manim、Edge TTS、本地/程序化图片、测试依赖） |
| `uv sync --locked --extra llm` | + 内置 LLM Planner（OpenAI 兼容接口） |
| `uv sync --locked --extra pexels` | + Pexels 图库搜索 Provider |
| `uv sync --locked --extra export` | + OTIO 时间线与 CMX3600 EDL 导出 |
| `uv sync --locked --all-extras` | 全部可选功能（推荐开发与运行完整测试时使用） |

<details>
<summary>Windows 下配置 FFmpeg PATH 示例</summary>

```powershell
$env:PATH += ";D:\ffmpeg\bin"
ffmpeg -version
ffprobe -version
```
</details>

---

## 使用指南

`markdown2video` 提供三种使用入口：

| 模式 | 适用场景 | 入口命令 |
|---|---|---|
| **Markdown 直转** | 快速把结构化文稿转为配音图文视频 | `python -m md2video script.md` |
| **Plan JSON 驱动** | 精确控制分镜、布局、素材策略与 TSX 表现组件 | `python -m md2video --plan plan.json` |
| **Agent Skill 编排** | 让外部 Agent 阅读材料、选择讲解风格、编写 Plan 并出片 | `/skill:md2video` |

### 1. Markdown 脚本直转

内置解析器并非通用富文本 Markdown 渲染器，仅识别标题层级、分割线与媒体标记（忽略表格、代码块等富文本语法）：

- `# 主标题` / `## 副标题`：仅显示在片头标题卡，不生成配音（多次出现时保留最后一个）。
- `### 小节标题`：开启一个正文小节，标题文本既显示在画面上也生成配音。
- **正文段落**：写在 `###` 下方，按中文标点自动断句并生成配音。**注意：第一个 `###` 之前的正文会被忽略。**
- `---`：开启附录部分，其后正文同样按句朗读。
- **媒体声明与区间标记**：在文件顶部（标题前）声明本地音频/图片路径（相对于 Markdown 文件所在目录解析），在正文中用独占一行的 `[music_start ...]` / `[image_start ...]` 标记生效区间。

完整带媒体标记的示例：

```markdown
[music:name="bgm",src="./music.mp3"]
[image:name="logo",src="./logo.png"]

# 主标题
## 副标题

### 第一节
这一段没有背景音乐。
[music_start bgm]
这段文字播放时会有背景音乐。
[image_start logo]
这段文字播放时还会显示图片。
[image_end logo]
[music_end bgm]

---
下面是附录内容。
```

### 2. PlanManifest JSON 驱动

当需要精细控制分镜、布局或挂载组件时，可直接编写或由 Agent 生成 `PlanManifest`（当前版本为 `"2"`，加载旧版 v1 时会自动迁移）。Plan 只声明内容、分镜和视觉意图，不包含具体时长。

最小 `plan.json` 示例：

```json
{
  "version": "2",
  "segments": [
    {"id": "title", "text": "计划驱动视频", "segment_type": "title_main"},
    {
      "id": "body",
      "text": "内容与画面策略分离，时间由实际执行产生。",
      "segment_type": "content",
      "audio_request": {"voice": "zh-CN-YunxiNeural", "speed": 1.0}
    }
  ],
  "scenes": [
    {"id": "intro", "shots": [{"id": "shot_intro", "segment_ids": ["title"]}]},
    {"id": "main", "shots": [{"id": "shot_main", "segment_ids": ["body"]}]}
  ]
}
```

执行命令：

```bash
uv run --all-extras python -m md2video --plan plan.json -o output.mp4 --subtitles
```

**核心字段说明：**

- **`segments`**：内容单元，共 5 种 `segment_type`：`title_main`、`title_sub`、`section_header`、`content`、`appendix`。**未声明 `audio_request` 的段落视为静默段**，不会自动配音。
- **`shots`**：连续镜头单元，通过 `segment_ids` 按序引用内容（每个 Segment 必须且只能被引用一次，ID 全局唯一），可在 `cues` 中挂载媒体区间标记或显式停留（hold cue）。
- **`scenes`**：一组共享视觉策略的镜头集合，可配置：
  - `visual_type` / `visual_params`：画面素材来源（见下表）。
  - `layout_type` / `layout_params`：内置 `center_title_body`、`full_bleed_image_caption_bottom`、`image_top_text_bottom` 三种模板，或通过 `layout_regions` 提交归一化坐标。
  - `render_backend`：`manim` 或 `remotion`（未指定时跟随全局配置；相邻同后端 Scene 自动合并渲染）。
  - `component`：挂载的表现组件引用（格式 `id@MAJOR.MINOR.PATCH`，仅 `remotion` 支持）。

**内置视觉素材供给（`visual_type`）：**

| `visual_type` | 素材供给方式 | 关键 `visual_params` |
|---|---|---|
| `text_only` | 纯文字排版，无额外图片 | 无 |
| `stock_image` | 本地图片或 Pexels 图库搜索 | 本地：`preferred_provider: "local"` + `path`<br>Pexels：`query`（需配置 `PEXELS_API_KEY`） |
| `gen_image` | Pillow 确定性程序化抽象插画（非 AI 语义生图） | 必填 `prompt`（作随机种子）；可选 `style`（`orbit` / `layers` / `waves` / `blocks`）、`palette`（`ink` / `moss` / `dusk`）、`width`、`height` |

**在 Plan 中声明 BGM 与图片区间：**

在根节点 `media_declarations` 声明资源路径，并在 Shot 的 `cues` 中声明起止（不在镜头开头时可通过 `position: "before" | "after"` 配合 `anchor_segment_id` 锚定，不直接填秒数）：

```json
{
  "media_declarations": {"music": {"calm": "assets/calm.wav"}},
  "cues": [
    {"id": "music_start_001", "cue_type": "marker_music", "kind": "start", "name": "calm", "position": "start"}
  ]
}
```

### 3. 使用表现组件（Remotion）

表现组件用于接管 Scene 的正文区域画面，自带独立的配色、排版与确定性动效。内置已验收组件如下：

| 组件引用 | 适用场景 | 挂载粒度 |
|---|---|---|
| `step_list@1.0.2` | 步骤、要点列表逐条浮现 | `shot`（单镜头独立） |
| `code_display@1.0.0` | 代码面板展示与语法着色 | `shot`（单镜头独立） |
| `terminal@1.0.0` | 终端命令与输出窗口展示（纯展示，不执行命令） | `shot`（单镜头独立） |
| `math_canvas@1.5.1` | 单位圆、正弦/余弦函数同步连续演示画布 | `scene`（跨镜头累积状态） |

> **注意**：使用组件的 Scene 必须运行在 `remotion` 后端。若组件名未找到，管线会回退至默认渲染并记录 `warning`；若版本号格式错误或指定了 `manim` 后端，则会直接报错。

### 4. Agent Skills 编排

仓库在 `skills/` 目录下内置了 3 个面向 Coding Agent（如 Pi）的 Skill，支持让 Agent 阅读文章或题目、规划分镜、生成 `PlanManifest` 并调用 CLI 出片：

| Skill | 职责与适用场景 | 示例 Plan |
|---|---|---|
| [`md2video`](skills/md2video/SKILL.md) | 总入口：介绍仓库能力、路由讲解风格、运行计划与排查产物 | — |
| [`md2video-tech-explainer`](skills/md2video-tech-explainer/SKILL.md) | 技术讲解视频：钩子、原理解析、步骤/代码/终端组件演示与总结 | [`cache.plan.json`](skills/md2video-tech-explainer/examples/cache.plan.json) |
| [`md2video-math-explainer`](skills/md2video-math-explainer/SKILL.md) | 数学直觉可视化：对象关系与连续同步演示（当前内置单位圆与正余弦画布） | [`unit-circle.plan.json`](skills/md2video-math-explainer/examples/unit-circle.plan.json) |

公共参考文档位于 [`skills/md2video/references/`](skills/md2video/references/)（含 [Plan 契约](skills/md2video/references/plan.md)、[运行参考](skills/md2video/references/runtime.md)、[组件参考](skills/md2video/references/components.md)）。

**在 Pi 中使用（本仓库 `.pi/settings.json` 已预置项目级注册）：**

```text
/skill:md2video 介绍这个仓库的能力，帮我选择视频风格
/skill:md2video-tech-explainer 把这篇技术文章编排成讲解视频
/skill:md2video-math-explainer 用单位圆讲解正弦与余弦
```

也可以在其他工作目录通过[标准库启动器 `run.py`](skills/md2video/scripts/run.py) 调用（参数路径相对于当前工作目录解析）：

```bash
python "<仓库绝对路径>/skills/md2video/scripts/run.py" --plan "./work/plan.json" -o "./work/video.mp4" --artifacts "./work/artifacts" --planner rule --subtitles
```

### 5. LLM Planner（可选）

对于普通 Markdown 输入，默认使用确定性的 **Rule Planner**（按标题层级与字数切分场景，无需 API Key）。

如需启用内置 **LLM Planner**（两阶段规划：先定场景视觉模板，再将连续原文映射为镜头，若打乱原文顺序或失败则自动回退至 Rule Planner），可复制 `.env.example` 为 `.env` 并配置 OpenAI 兼容接口：

```env
MD2VIDEO_PLANNER=llm
OPENAI_API_KEY=sk-your-key-here
MD2VIDEO_LLM_MODEL=openai:gpt-4o
# MD2VIDEO_LLM_BASE_URL=https://your-api-endpoint/v1
```

```bash
uv run --all-extras python -m md2video script.md --planner llm -o output.mp4
```

> **提示**：内置 LLM Planner 仅负责 `text_only` / `stock_image` 分镜与内置布局选择，不会自动挂载 TSX 表现组件。需要组件编排时请使用 **Agent Skills** 生成 `PlanManifest`。

---

## CLI 与环境变量参考

### 命令行参数

```text
uv run --all-extras python -m md2video INPUT.md [选项]
uv run --all-extras python -m md2video --plan PLAN.json [选项]
```

（`INPUT.md` 与 `--plan` 二选一，互斥必填）

| 参数 | 说明 | 默认值 |
|---|---|---|
| `-o, --output FILE` | 输出 MP4 文件路径 | `output.mp4` |
| `--plan FILE` | 直接执行指定的 `PlanManifest` JSON，跳过 Markdown 解析与规划 | 无 |
| `--planner {rule,llm}` | Markdown 入口使用的规划器（优先于环境变量） | `MD2VIDEO_PLANNER`（默认 `rule`） |
| `--voice VOICE` | 覆盖全局/段落的 Edge TTS 语音名称 | `zh-CN-YunxiNeural` |
| `--speed SPEED` | 覆盖 TTS 语速倍率（正数，如 `1.1` 加速、`0.9` 放慢） | `1.0` |
| `--artifacts DIR` | 缓存（`tts/`、`images/`）与运行产物（`runs/`）根目录 | `artifacts/` |
| `--subtitles` | 将有配音的 `content` / `appendix` 字幕烧录进视频画面（ASS） | 关闭 |
| `--bundle` | 在当前 run 目录额外导出分段视频 clips、SRT、EDL 与素材拷贝 | 关闭 |

### 环境变量

项目启动时通过 `python-dotenv` 自动加载根目录 `.env`（命令行显式参数优先级高于环境变量）：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `MD2VIDEO_PLANNER` | 默认规划器：`rule` 或 `llm` | `rule` |
| `MD2VIDEO_RENDER_BACKEND` | 全局默认渲染后端：`manim` 或 `remotion` | `manim` |
| `OPENAI_API_KEY` | 内置 LLM Planner 的 API Key | 无 |
| `MD2VIDEO_LLM_MODEL` | LLM 模型名称（可带 `openai:` 前缀） | `openai:gpt-4o` |
| `MD2VIDEO_LLM_BASE_URL` | OpenAI 兼容接口 Base URL | 无 |
| `PEXELS_API_KEY` | 启用 Pexels 图片搜索 Provider 的 API Key | 无 |
| `MD2VIDEO_STYLE_PACK` | 内置视觉设计包名称 | `ink_night` |
| `MD2VIDEO_STYLE_PACK_FILE` | 外部自定义 `ThemeTokens` JSON 文件路径 | 无 |
| `MD2VIDEO_KEN_BURNS` | 是否开启叠加图片的缓慢缩放动效 | `true` |
| `MD2VIDEO_KEN_BURNS_SPEED` | Ken Burns 每帧缩放因子 | `0.001` |
| `MD2VIDEO_KEN_BURNS_DIRECTION` | Ken Burns 缩放方向：`in` 或 `out` | `in` |
| `MD2VIDEO_LAYOUT_CONSTRAINTS` | 附加布局约束 Python 模块（逗号分隔） | 无 |
| `MD2VIDEO_COMPONENTS` | 运行期额外加载的组件注册模块（逗号分隔） | 无 |

---

## 工作原理与管线架构

### 核心设计原则：视频编译器，而非自由发挥的 Agent

`markdown2video` 将视频生成拆解为职责严格隔离的四类数据契约与四个执行阶段：

```text
Markdown ─→ Parser ─→ Planner ─┐
                               ├─→ PlanManifest ─→ ExecutionAssets ─→ 渲染后端 (Manim / Remotion)
PlanManifest JSON ─────────────┘                                                ↓
                                             MP4 ← FFmpeg Assembler ← Timeline (不变量校验)
                                              ↓
                                   FinalResult + Viewer + OTIO / Bundle
```

1. **四份核心数据记录（单向流动，互不回写）**：
   - **`PlanManifest` (`plan.json`)**：仅记录内容、分镜与视觉/组件编排意图，不含具体时长，也不含颜色字号等具象样式值。
   - **`ThemeTokens`（设计包）**：全局配色、字体、安全区与停顿节奏的唯一来源。
   - **`ExecutionAssets` (`execution-assets.json`)**：记录工具执行后的客观事实（TTS 音频实测时长、图片路径与尺寸）。
   - **`Timeline` (`timeline.json`)**：由渲染后端产出的真实时间窗、画面文字与 marker 区间账本。时长裁决遵循单一纯函数优先级：**音频实测事实 > 显式 hold cue > 设计包默认节奏**。
2. **四道确定性校验门禁**：
   - **布局合法**：区域不重叠、不越出安全区、不小于最小尺寸、文字不溢出容量。
   - **样式合法**：设计包 Token 取值均在受控范围内。
   - **时间线合法**（`md2video/timeline/invariants.py`）：镜头完整覆盖、严格有序、不重叠，cue 归属正确。
   - **交付合法**：结果字段完整、产物文件真实存在、成片时长与时间线一致。
3. **两套受控扩展机制**：
   - **Tool（Python Provider）**：负责获取素材与执行渲染（TTS、图片、渲染后端均实现统一的 `Tool` 协议并通过注册表调度）。
   - **表现组件（TSX）**：负责正文画面演法，自带排版与动效，通过静态扫描、双跑一致性与黄金帧比对验收后按固定版本引用。

更详尽的架构演进与取舍请参考 [`docs/architecture.md`](docs/architecture.md)。

---

## 运行产物与质量检查

每次执行会在 `<artifacts>/runs/<run_id>/` 下创建独立目录（不会覆盖历史记录），TTS 与图片缓存分别存放在 `<artifacts>/tts/` 与 `<artifacts>/images/`：

| 产物文件 | 说明 |
|---|---|
| `plan.json` | 本次执行的完整 `PlanManifest` |
| `execution-assets.json` | 音频实测时长、图片尺寸与实际采用 Provider 的事实账本 |
| `timeline.json` | 通过不变量校验的真实镜头时间窗、显示文本与 marker 区间 |
| `result.json` | 运行摘要（`run_id`、`status`、输出路径、`warnings` 列表、产物清单） |
| `manifest_viewer.html` | 单文件静态可视化检查页，可直接用浏览器打开核对分镜与时间线 |
| `timeline.otio` | 可选导出的 OpenTimelineIO 交换文件 |
| `bundle/` | 开启 `--bundle` 时导出的分段视频、SRT 字幕、EDL 与素材拷贝 |

**推荐验收流程**：
1. 检查 `result.json` 中的 `status` 与 `warnings`（确认是否发生素材降级或组件回退）。
2. 在浏览器打开 `manifest_viewer.html` 核对镜头时长与素材绑定。
3. 根据 `timeline.json` 中的真实秒数使用 FFmpeg 抽帧检查画面排版：
   ```bash
   ffmpeg -y -ss <真实秒数> -i "<成片路径>" -frames:v 1 "<截图路径>"
   ```

---

## 能力边界与已知限制

为了保持管线的确定性与可维护性，本项目明确划定了以下边界：

- **不做运行期即兴代码生成**：制片过程中不会让大模型现场编写 Manim 或 React/TSX 动画代码；新增视觉演法必须先开发为表现组件并通过验收。
- **不做自主审美 Agent Harness / Web 编辑器**：框架提供确定性校验与静态检查页，但不内置自动看片返工循环、GUI 时间线编辑器或 MCP Server。
- **非 AI 语义生图 / 文生视频**：内置 `gen_image` 是基于 Pillow 的确定性程序化几何插画（相同参数字节级一致，`prompt` 仅作随机种子），不对接扩散模型或 Stock Video。
- **数学与代码组件范围受限**：`math_canvas` 目前仅内置单位圆与正弦/余弦演示，不支持任意数学公式证明动画；`code_display` 与 `terminal` 仅做静态/分步文本展示，不会真实执行命令。
- **朗读稿与显示稿同源**：Segment 的 `text` 同时用于 TTS 配音与画面/组件文本展示，暂不支持独立的口播稿与屏幕显示稿。
- **无沙箱隔离**：自定义 Python Provider、TSX 组件与注册模块均作为本地可信代码执行，请勿加载来源不明的扩展。

---

## 扩展开发

### 1. 注册自定义素材或渲染工具（Python Provider）

所有工具均遵循 [`md2video/tools/protocol.py`](md2video/tools/protocol.py) 中的 `Tool` 协议（提供 `tool_type`、`provider_name` 属性与 `execute(dict) -> dict` 方法，无需继承基类）。

以自定义本地图片 Provider 为例（`my_tools.py`）：

```python
from pathlib import Path
from PIL import Image


class CustomImageTool:
    @property
    def tool_type(self):
        return "image"

    @property
    def provider_name(self):
        return "custom-local"

    def execute(self, input_data):
        params = input_data["scene"]["visual_params"]
        path = Path(params["path"]).expanduser()
        if not path.is_absolute():
            path = Path(input_data.get("base_dir") or Path.cwd()) / path
        path = path.resolve(strict=True)
        with Image.open(path) as image:
            width, height = image.size
        return {"visuals": [{
            "shot_id": input_data["shot"]["id"],
            "path": str(path),
            "width": width,
            "height": height,
            "source": self.provider_name,
            "duration": 0.0,
        }]}
```

在自定义启动脚本中将工具注册到 `Pipeline` 实例并配置降级优先级：

```python
from md2video.config import ToolConfig
from md2video.core.pipeline import Pipeline
from my_tools import CustomImageTool

config = ToolConfig()
config.register("stock_image", ["custom-local", "local", "_text_only"])

pipeline = Pipeline(planner="rule", tool_config=config)
pipeline.registry.register("stock_image", CustomImageTool())
pipeline.run_plan("plan.json", "output.mp4")
```

### 2. 开发与验收表现组件（TSX）

表现组件源码位于 `md2video/components/sources/<component_id>/`，包含一个默认导出的 `.tsx` 文件与同目录的 `register.py`（可参考 [`step_list`](md2video/components/sources/step_list/step_list.tsx) 与 [`ComponentProps` 类型定义](md2video/tools/render/remotion_backend/src/registered/types.ts)）：

```python
from pathlib import Path
from md2video.components.registry import register_component


def displayed_texts(payload):
    # 必须与 TSX 实际渲染的文字一致（用于字幕去重判定）；纯图形组件返回 []
    return [str(seg["text"]) for seg in payload if seg.get("segment_type") == "content"]


register_component(
    "note_card", "1.0.0", "body", Path(__file__).with_name("note_card.tsx"),
    mount="shot",  # 跨镜头连续画布使用 "scene"
    displayed_texts=displayed_texts,
    register_module=__name__,
)
```

组件开发完成后，运行验收 CLI（执行禁用 API 静态扫描、固定夹具双跑一致性比对、黄金帧校验并自动安装至 Remotion 工程）：

```bash
uv run --locked --all-extras python -m md2video.check_component md2video.components.sources.note_card.register
```

### 3. 新增风格 Skill

1. 创建 `skills/md2video-<style-name>/SKILL.md`，声明清晰的 frontmatter `description`、适用内容、分镜结构、可用组件与验收步骤，并提供 `examples/*.plan.json`。
2. 在入口 [`skills/md2video/SKILL.md`](skills/md2video/SKILL.md) 中添加风格路由说明。
3. 更新 [`tests/test_skills.py`](tests/test_skills.py) 中的预期 Skill 集合并运行测试验证。

---

## 项目结构与测试

### 目录结构

```text
pyproject.toml / uv.lock   # Python 依赖声明与锁文件
md2video/
├── cli.py / __main__.py   # CLI 入口
├── config.py              # 默认配置与环境变量加载
├── core/                  # Pipeline 主流程、多后端分镜编排与 Rule/LLM Planner
├── manifest/              # PlanManifest、运行产物数据模型与 v1 -> v2 迁移
├── parser/                # Markdown 子集解析与中文分句
├── layout/                # 布局模板、几何约束、坐标换算与文字容量检查
├── style/                 # ThemeTokens、内置设计包与 Manim 样式实现
├── components/            # TSX 表现组件注册表、安装器与组件源码
├── check_component.py     # 表现组件确定性验收 CLI
├── tools/
│   ├── tts/               # Edge TTS 合成与缓存
│   ├── image/             # 本地图片、Pexels 搜索与 Pillow 程序化插画
│   └── render/            # Manim / Remotion 渲染工具、时间调度与 Remotion 工程
├── assembler/             # FFmpeg 视频拼接、图片/BGM 混音与 ASS 字幕烧录
├── timeline/              # 时间线不变量校验、时长裁决、OTIO 与 Bundle 导出
└── inspect/               # Run 目录管理与静态检查页 (manifest_viewer.html)
skills/                    # 内置 Agent Skills、公共参考文档与标准库启动器
evals/                     # 评测脚本、示例 Plan JSON 与测试素材
tests/                     # 单元测试与可选的真实渲染 Smoke 测试
docs/                      # 架构设计与背景文档
```

### 运行测试

运行默认单元测试套件（覆盖数据契约、规划顺序、缓存/降级路径、时间线不变量与 FFmpeg 合成，LLM 与 TTS 网络请求使用测试替身）：

```bash
uv sync --locked --all-extras
uv run --all-extras pytest -q
```

如需运行耗时较长的真实渲染 Smoke 测试（需已安装 Manim 与 Remotion 完整依赖）：

```powershell
$env:MD2VIDEO_RENDER_SMOKE = "1"
uv run --all-extras pytest tests/test_render_smoke.py tests/test_remotion_smoke.py tests/test_multi_backend.py tests/test_skills.py -q
```

---

## 许可证与支持

- **许可证**：本项目基于 [MIT License](LICENSE) 开源，可自由使用、修改与分发，保留版权与许可声明即可。
- **架构文档**：[docs/architecture.md](docs/architecture.md)
- **演进记录**：[CHANGELOG.md](CHANGELOG.md)
- **问题反馈**：欢迎提交可复现的 Issue。本项目目前已作为阶段性成果归档开源，不再承诺新功能开发或及时回复。
