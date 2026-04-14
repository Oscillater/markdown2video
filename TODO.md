# 项目设计文档：Markdown 驱动的视频生成框架

**Project Name:** md2video
**Version:** 0.2

---

## 1. 核心定位

这是一个以 **Markdown 脚本为输入，自动生成视频的编排框架**。

框架负责主流程的编排与组装：解析脚本、切分语义段落、构建时间轴、调度外部工具、最终拼接成片。

外部能力（语音合成、图片获取、视频片段渲染）以**工具（Tool）**的形式接入，返回受限的结构化结果。

语义决策（如判断某段文字适合用什么视觉形式）可以由 **LLM（Planner）** 完成，也可以由**规则代码**完成。两者是等价的、可互换的处理节点，框架不依赖 Agent 稳定运行。

**一句话定位：框架是稳定内核，工具是可替换执行器，Planner 是可选的语义增强。**

---

## 2. 分层架构

```
┌─────────────────────────────────────────┐
│              用户 Markdown               │  输入层
└────────────────────┬────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│           Framework Core（框架核心）      │
│                                         │
│  Parser → Segmenter → Planner → Executor│  编排层
│    (Shot 划分+Scene 聚合+视觉决策)      │
│               ↑                         │
│          Manifest（中间状态）            │
│   ┌─────┬────────┬──────┐              │
│ Segments Shots  Scenes                  │  三层数据模型
└────────────────────┬────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│              Tools（工具层）              │
│                                         │
│   TTS Tool │ Image Tool │ Render Tool   │  执行层
│         (按 Shot 粒度调用，Scene 作上下文)│
└────────────────────┬────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│            Assembler（合成层）           │  输出层
│         FFmpeg 统一拼接，输出 MP4        │
└─────────────────────────────────────────┘
```

**核心变化：引入 Shot（镜头）+ Scene（风格组）两层概念。**

- **Segment** 是最小时间单元（一句话），保持不变
- **Shot** 是连续的最小视觉单元，由连续的 Segment 组成，每个 Shot 调用一个工具
- **Scene** 是风格分组，由 Planner 将多个 Shot 聚合而成，共享同一个视觉方案
- Planner 同时负责三件事：① Shot 划分（哪些连续句子属于同一镜头）② Scene 聚合（哪些镜头风格一致）③ 视觉决策（每个 Scene 用什么视觉呈现）

---

## 3. 核心模块

### 3.1 Parser（解析器）

**归属：框架内建，不可替换。**

将 Markdown 文本编译为内部结构，处理：

- `# / ## / ###` 标题层级
- 段落文本
- 显式媒体标记：`[music:...]`、`[image:...]`、`[music_start name]`、`[image_start name]` 等

**用户在 Markdown 中的显式指令具有最高优先级，Planner 不得覆盖。**

---

### 3.2 Segmenter（分段器）

**归属：框架内建，可由 Planner 辅助优化。**

将解析后的文本切分为**语义段（Segment）**，每个 Segment 是最小的时间单元（通常一句话）。

默认行为：基于标点和长度的规则分句（当前 `md_parser.py` 中 `custom_sentence_split` 的逻辑）。

Segment 是最小粒度，不可再拆。TTS 以 Segment 为单位合成语音。

### 3.2.1 Scene（风格组）与 Shot（镜头）

**归属：Planner 的输出，不属于 Parser。**

#### Shot（镜头）

Shot 是**时间连续的最小视觉单元**，由 Planner 将连续的 Segment 分组而成。

- 一个 Shot 包含 1~N 个**连续** Segment
- 一个 Segment 只属于一个 Shot
- Shot 有明确的 start/end（由其所含 Segment 的 TTS 时长累加得出）
- 每个 Shot 调用一个工具，生成一段连续的画面

#### Scene（风格组）

Scene 是**语义级别的风格分组**，由 Planner 将多个 Shot 聚合而成。同一个 Scene 下的所有 Shot 共享同一种视觉风格和工具类型。

- 一个 Scene 包含 1~N 个 Shot（Shot 之间可以不连续）
- 一个 Shot 只属于一个 Scene
- Scene 定义 `visual_type` + `visual_params`，调用工具时将整个 Scene 塞入上下文
- Scene 本身没有时间跨度，它的 start/end 由其包含的所有 Shot 的 start/end 聚合得出

**为什么需要两层：**
- Shot 保证时间连续性：每个 Shot 对应一段连续画面，工具按 Shot 粒度生成视频/图片
- Scene 保证风格一致性：多个讲"神经网络"的镜头可能散落在不同时间点，但它们共享同一套视觉风格和工具参数
- Planner 在 Scene 层做语义决策，Tool 在 Shot 层执行生成

**示例：**
```
Scene 1: "AI 概念" — visual_type="stock_image"
  ├── Shot 1: "神经网络就像一个复杂的大脑" / "它由大量的人工神经元组成"    ← 连续
  │     调用 Image Tool(query="neural network", context=整个 Scene 1)
  └── Shot 2: "深度学习是神经网络的一种" / "它在图像识别方面表现出色"       ← 连续
        调用 Image Tool(query="deep learning", context=整个 Scene 1)

Scene 2: "总结" — visual_type="text_only"
  └── Shot 3: "以上就是今天的全部内容"                                     ← 连续
        调用 Manim Render(context=整个 Scene 2)
```

---

### 3.3 Manifest（清单）

**框架最核心的中间数据结构。**

Manifest 分为两个阶段，每个阶段都有 Segment 层、Shot 层和 Scene 层：

#### Plan Manifest（规划清单）——执行前

描述"要做什么"，由 Parser + Planner 共同生成：

```json
{
  "version": "1",
  "segments": [
    {
      "id": "seg_001",
      "text": "神经网络就像一个复杂的大脑",
      "visual_type": "stock_image",
      "visual_params": {
        "query": "neural network abstract"
      },
      "audio_request": {
        "voice": "zh-CN-YunxiNeural",
        "speed": 1.0
      },
      "explicit": false
    }
  ],
  "media_declarations": {
    "music": { "bgm": "./music.mp3" },
    "images": { "logo": "./assets/logo.png" }
  }
}
```

`explicit: true` 表示该项来自 Markdown 显式指令，Planner 不得修改。

#### Plan Manifest 中的 Scene 与 Shot

Planner 产出的分组结构填入 Plan Manifest：

```json
{
  "scenes": [
    {
      "id": "scene_001",
      "visual_type": "stock_image",
      "visual_params": {
        "query": "neural network abstract"
      },
      "section_context": "什么是神经网络",
      "shots": [
        {
          "id": "shot_001",
          "segment_ids": ["seg_001", "seg_002", "seg_003"]
        },
        {
          "id": "shot_002",
          "segment_ids": ["seg_004", "seg_005"]
        }
      ]
    },
    {
      "id": "scene_002",
      "visual_type": "text_only",
      "visual_params": {},
      "section_context": "什么是神经网络",
      "shots": [
        {
          "id": "shot_003",
          "segment_ids": ["seg_006", "seg_007"]
        }
      ]
    }
  ]
}
```

**三层关联关系：**
- `Scene.shots[].segment_ids` → 引用属于该 Shot 的 Segment ID 列表（连续 segment）
- Segment 上的 `visual_type` / `visual_params` 由所属 Scene 决定（冗余存储，方便渲染时直接读取）
- 工具调用时：输入一个 Shot + 其所属 Scene 的完整上下文

#### Result Manifest（产物清单）——执行后

记录"已经做出了什么"，由 Executor 填充：

```json
{
  "segments": [
    {
      "id": "seg_001",
      "audio": {
        "path": "./artifacts/seg_001.mp3",
        "duration": 4.2,
        "provider": "edge-tts"
      },
      "start": 0.0,
      "end": 4.2
    }
  ]
}
```

注：Segment 的视觉信息不再单独记录（视觉由 Scene + Shot 统一管理）。

#### Result Manifest 中的 Scene 与 Shot

Shot 的结果记录每个镜头的时间范围和视觉产物，Scene 聚合其下所有 Shot 的结果：

```json
{
  "scenes": [
    {
      "id": "scene_001",
      "shots": [
        {
          "id": "shot_001",
          "segment_ids": ["seg_001", "seg_002", "seg_003"],
          "start": 0.0,
          "end": 12.5,
          "visual": {
            "path": "./artifacts/shot_001_bg.jpg",
            "width": 1080,
            "height": 1920,
            "source": "pexels"
          }
        },
        {
          "id": "shot_002",
          "segment_ids": ["seg_004", "seg_005"],
          "start": 12.5,
          "end": 20.0,
          "visual": {
            "path": "./artifacts/shot_002_bg.jpg",
            "width": 1080,
            "height": 1920,
            "source": "pexels"
          }
        }
      ]
    }
  ]
}
```

`ShotResult.start/end` 由其所含 Segment 的音频时长累加得出。`visual` 字段记录该 Shot 的视觉产物（图片、视频等），由工具填充。SceneResult 聚合其下所有 Shot 的时间范围和视觉产物。

---

### 3.4 Planner（规划器）

**归属：可替换的处理节点，非必需。**

Planner 的职责：接收 Segment 列表，完成三件事：
1. **语义分组**：将连续的 Segment 合并为 Shot（镜头）
2. **风格聚合**：将多个 Shot 聚合为 Scene（风格组）
3. **视觉决策**：为每个 Scene 补全 visual_type 和 visual_params

**Planner 是一个接口，有两种实现：**

#### A. Rule Planner（规则规划器）
纯代码逻辑，基于关键词、段落长度、上下文规则来决定分组和视觉方案。
- 稳定、可预测、无需 API Key
- 推荐作为默认和 fallback
- 当前实现：所有 Scene 默认 `visual_type="text_only"`，分组逻辑基于 segment 类型和字符数

#### B. LLM Planner（语言模型规划器）
调用外部 LLM API，做语义理解后返回结构化决策。
- 需要用户配置 API Key
- 只用于语义判断，**不负责生成代码或直接操作文件**
- 输出必须符合 Planner Schema（见下文），框架做强校验
- 能理解文本语义，为 Scene 选择合适的 visual_type 和 visual_params（如图片搜索 query）
- 能将不连续但风格一致的 Shot 聚合为同一 Scene

#### Planner 接口约定

输入（完整的 Segment 列表 + 上下文）：
```json
{
  "segments": [
    {"id": "seg_001", "text": "神经网络就像一个复杂的大脑", "section": "什么是神经网络"},
    {"id": "seg_002", "text": "它由大量的人工神经元组成", "section": "什么是神经网络"},
    {"id": "seg_003", "text": "深度学习是神经网络的一种", "section": "深度学习"}
  ],
  "media_declarations": {"music": {}, "images": {}},
  "available_visual_types": ["text_only", "stock_image", "stock_video", "manim"]
}
```

输出（必须严格符合 schema — 包含 Scene 分组 + Shot 划分 + 视觉决策）：
```json
{
  "scenes": [
    {
      "id": "scene_001",
      "visual_type": "stock_image",
      "visual_params": {
        "query": "neural network abstract"
      },
      "shots": [
        {"id": "shot_001", "segment_ids": ["seg_001", "seg_002"]},
        {"id": "shot_002", "segment_ids": ["seg_003"]}
      ],
      "section_context": "什么是神经网络"
    },
    {
      "id": "scene_002",
      "visual_type": "text_only",
      "visual_params": {},
      "shots": [
        {"id": "shot_003", "segment_ids": ["seg_004"]}
      ],
      "section_context": "深度学习"
    }
  ]
}
```

**两种 Planner 的输出 schema 完全相同。框架只消费 schema，不关心谁生成的。**

---

### 3.5 Tools（工具层）

工具是框架的外部执行器。每个工具契约：**固定输入（JSON）→ 执行 → 固定输出（JSON）+ 产物文件**。

工具不持有全局状态，不做拼接，不做编排。

**工具与框架语言无关**：工具可以用任何语言实现（Python、TypeScript、Go 等），框架只关心输入输出的 JSON 契约。执行方式由适配器决定：

| 执行方式 | 示例 | 适用场景 |
|----------|------|----------|
| 进程内调用 | `EdgeTTSTool.synthesize()` | Python 实现的工具，直接 import 调用 |
| CLI 子进程 | `ffmpeg -i ...` | 命令行工具，通过 stdin/stdout 传 JSON |
| HTTP API | `POST /render` → Remotion 服务 | 独立服务（如 Node.js 的 Remotion），通过 HTTP 调用 |
| 外部 API | Pexels / Pixabay REST API | 第三方云服务 |

**工具接口 Protocol 只定义 JSON 契约，不绑定执行方式**。每种执行方式对应一个适配器（Adapter），Pipeline 通过适配器统一调度。适配器负责：
- 进程内 → 直接调用方法，返回 dict
- CLI → 子进程执行，解析 stdout JSON
- HTTP → 发送请求，解析响应 JSON
- 外部 API → HTTP 客户端调用，解析响应

工具按产物类型分为三大类：

#### Audio Tools（音频工具）

处理语音合成、音效生成等。

**TTS Tool（已实现：edge-tts）**

输入：
```json
{
  "text": "你好，世界",
  "voice": "zh-CN-YunxiNeural",
  "speed": 1.0,
  "format": "mp3"
}
```

输出：
```json
{
  "path": "./artifacts/xxx.mp3",
  "duration": 2.34,
  "provider": "edge-tts",
  "cache_key": "abc123"
}
```

#### Image Tools（图片工具）

处理静态图片的获取和生成。

**Image Search Tool（计划中：Pexels / Pixabay）**

输入：
```json
{
  "query": "futuristic city AI",
  "source": "pexels",
  "orientation": "portrait"
}
```

输出：
```json
{
  "path": "./artifacts/xxx.jpg",
  "width": 1080,
  "height": 1920,
  "source_url": "...",
  "license": "free",
  "cache_key": "def456"
}
```

#### Video Tools（视频工具）

处理视频片段的生成和渲染。

**Manim Render Tool（当前）**

按 Shot 粒度驱动，每个 Shot 决定一组连续 Segment 的视觉呈现方式。调用时将所属 Scene 的完整上下文传入：

输入（一个 Shot + 其包含的 Segment 结果 + 所属 Scene 上下文）：
```json
{
  "shot": {
    "id": "shot_001",
    "segment_ids": ["seg_001", "seg_002"]
  },
  "scene": {
    "id": "scene_001",
    "visual_type": "text_only",
    "visual_params": {},
    "section_context": "什么是神经网络"
  },
  "segments": [
    {"id": "seg_001", "text": "...", "audio": {"path": "...", "duration": 3.5}},
    {"id": "seg_002", "text": "...", "audio": {"path": "...", "duration": 4.2}}
  ]
}
```

输出（渲染后的视频片段 + 时间轴）：
```json
{
  "path": "./artifacts/scene_001.mp4",
  "duration": 7.7,
  "width": 480,
  "height": 854,
  "cache_key": "ghi789",
  "timeline": {
    "seg_001": {"start": 0.0, "end": 3.5},
    "seg_002": {"start": 3.5, "end": 7.7}
  }
}
```

---

### 3.6 Assembler（合成器）

**归属：框架内建，使用 FFmpeg 作为唯一合成引擎。**

消费 Result Manifest（Segment + Shot + Scene），执行：

1. 按时间轴拼接所有 Shot 对应的视频片段
2. 混入 TTS 音轨
3. 叠加背景音乐（含音量控制、淡入淡出）
4. 叠加图片 Overlay（基于 Shot 的 visual 结果，含 Pan/Zoom 动效）
5. 可选：烧录字幕
6. 导出最终 MP4

Assembler 不关心片段从哪里来，只消费标准化产物。

---

### 3.7 时长对齐（Duration Alignment）

**这是框架必须解决的核心问题之一。**

一个 Shot 的最终时长由多个来源决定，它们往往不一致：

| 来源 | 产出 | 特点 |
|------|------|------|
| TTS（Audio Tool） | Segment 级别的音频时长 | 每句话一个文件，时长由语速+文本长度决定 |
| Render（Video Tool） | Shot 级别的视频时长 | 可能是 Manim 动画时长、Remotion 渲染时长、AI 视频固定时长 |
| Image（Image Tool） | 无时长 | 静态图片需要 Framework 决定展示多久 |
| AI 视频生成 | 固定时长（如 4s/8s/16s） | 与 TTS 时长往往不匹配 |

**对齐策略：以 TTS 时长为主轴，其他工具适配。**

1. **TTS 时长 = 主时间轴**：每个 Segment 的 TTS 音频时长决定该 Segment 的 start/end，累加得出 Shot 的总时长。这是不可变的基础时间线。

2. **Render Tool 适配**：Manim/Remotion 等渲染工具需要接收目标时长，渲染出与 TTS 时长匹配的视频。例如 Manim 中通过 `self.wait()` 填充时间。

3. **Image Tool 适配**：静态图片无固有时长，由 Shot 时长决定展示时长。Assembler 通过 ffmpeg 的 `-t` 参数控制图片 overlay 的持续时间。

4. **AI 视频生成适配**：AI 生成的视频有固定时长（如 4s），可能短于或长于对应 Shot 的 TTS 时长。Framework 需要处理：
   - **AI 视频较短**：循环播放、慢放（`setpts=2*PTS`）、或截取最后帧静帧填充
   - **AI 视频较长**：裁剪（`-t` 参数）、加速、或只取关键片段
   - **永远不截断 TTS**：语音内容必须完整播放，视觉可以适配

5. **时长差异的阈值警告**：当 AI 生成视频与目标时长差异超过阈值（如 >50%），Framework 记录 warning 但不中断流程。

**一句话：TTS 说多久，视频就多久。视觉素材去适配语音，而不是反过来。**

---

## 4. 工具优先级

框架不硬编码 Fallback 逻辑，工具选择由两层协作完成：**LLM 指定 Provider，用户优先级序列兜底**。

**设计原则**：
- "Fallback"本质是工具优先级问题，应由用户控制，而非框架硬编码
- **LLM Planner 负责选择工具**：为每个 Scene 决定 `visual_type` 并可在 `visual_params.preferred_provider` 中指定首选 Provider（如 `pexels`）
- **用户优先级序列兜底**：LLM 指定的 Provider 失败后，按用户配置的 `tool_priority` 序列依次尝试剩余选项
- 不同 `visual_type` 的容错策略差异很大，强行统一为 L1/L2/L3 三级反而别扭

**用户配置示例**：

```yaml
# config.yaml
tool_priority:
  stock_image:
    - pexels          # 优先 Pexels
    - pixabay         # Pexels 失败用 Pixabay
    - _text_only      # 都没有就降级为纯文字

  stock_video:
    - pexels_video
    - pixabay_video
    - _text_only

  tts:
    - edge-tts        # 优先 edge-tts
    - azure-tts       # edge-tts 失败用 Azure

  text_only:
    - manim           # 只有一种实现，无需降级
```

**执行逻辑**：
1. Pipeline 收到 Shot 的 `visual_type`（由 Planner 决定）和 `visual_params.preferred_provider`（可选，LLM 指定）
2. 如果有 `preferred_provider`，优先尝试该 Provider
3. `preferred_provider` 失败（或未指定），查 `tool_priority[visual_type]` 获取用户配置的优先级序列
4. 按顺序尝试序列中的每个 Provider，跳过已尝试过的，第一个成功即返回结果
5. 特殊标识 `_text_only` 表示降级为纯文字渲染（Manim），不需要额外 Provider
6. 全部失败 → 记录 warning，该 Shot 降级为 `text_only`

**示例**：LLM 为某 Scene 指定 `visual_type="stock_image"`, `preferred_provider="pexels"`
→ 优先用 Pexels → Pexels 失败 → 按用户序列尝试 Pixabay → 都失败 → 降级为 `text_only`

**注意**：`visual_params.fallback` 字段已废弃。`visual_params.preferred_provider` 是 LLM 的建议，用户优先级序列是最终兜底。

---

## 5. 缓存机制

缓存由框架统一管理，工具本身不维护缓存。

缓存键（`cache_key`）由工具输入参数的哈希生成：

- 相同文本 + 相同 voice → 复用 TTS 音频
- 相同 query + 相同 source → 复用下载素材
- 相同模板 + 相同参数 → 复用渲染片段

缓存存储在 `./cache/` 目录，按工具类型分子目录。

---

## 6. 配置与 API Key

用户在项目根目录的 `.env` 或 `config.yaml` 中填写：

```yaml
tool_priority:
  stock_image:
    - pexels
    - pixabay
    - _text_only

  tts:
    - edge-tts          # 无需 key
    - azure-tts

providers:
  image:
    pexels:
      api_key: ${PEXELS_API_KEY}
    pixabay:
      api_key: ${PIXABAY_API_KEY}
  tts:
    azure-tts:
      api_key: ${AZURE_TTS_KEY}

  planner:
    default: rule              # 默认使用规则，不需要 key
    llm:
      provider: openai
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
```

框架通过配置文件决定调用哪个 provider，不在代码中硬编码任何 key。

---

## 7. 关键设计原则

1. **Markdown 显式指令最高优先级**，框架规则其次，Planner 补全最后。
2. **Planner 是可替换接口**，LLM Planner 和 Rule Planner 输入输出 schema 完全相同，框架按配置选择，LLM 不可用时自动 fallback。
3. **工具只做一件事**，不持有状态，不做全局编排。
4. **合成由 FFmpeg 统一执行**，工具只产出原始素材。
5. **Manifest 是唯一数据流**，不允许工具之间直接通信。
6. **Segment 是 TTS 的单位，Shot 是时间连续的最小视觉单元，Scene 是风格分组**。三层各司其职，通过 Manifest 关联。

---

## 8. 开发路线图

### Phase 1：基础架构 ✅

Manifest schema、Scene 数据模型、Rule Planner、Scene 粒度渲染、FFmpeg 合成、单元测试。
→ `changelog/phase1.md`

### Phase 2：Shot 层 + LLM Planner ✅

引入 Shot（镜头）作为最小视觉单元；实现 LLM Planner 两阶段方案（Blueprint → Chunk Mapping → Reconcile）。
→ `changelog/phase2a_scene_architecture.md`, `changelog/phase2b_llm_planner.md`

### Phase 3：Tool 接口 + 基础设施 ✅

Tool Protocol + Adapter + Cache + Registry + Priority Dispatch + 时长对齐契约。
→ `changelog/phase3_tool_infrastructure.md`

**当前状态**：229 tests passing。所有 scene 为 text_only，Pipeline 按 Registry 调度工具。

---

### Phase 4：现有工具重构

目标：修正代码与架构规范的偏差，打通 Phase 5 路径。

#### 4A：Pipeline per-Shot 工具调度

当前 `_dispatch_render()` 将所有 scene 统一交给 Manim 批量渲染，不区分 visual_type。`_invoke_tool()` 对非 manim 工具直接 `raise NotImplementedError`。

- [ ] `_dispatch_render()` 按 scene 的 visual_type 分发：`text_only` 走现有 Manim 路径，其他类型走 Tool.execute()
- [ ] `_invoke_tool()` 实现通用 Tool 调用（当前只特判 manim）
- [ ] Tool 执行成功后填充 `ShotResult.visual`（当前始终为空默认值）

#### 4B：Assembler 消费 per-Shot 视觉产物

当前 `FFmpegAssembler` 将视频视为单一资产，scene 循环对非 text_only 是 no-op。

- [ ] 遍历 `result.scenes[].shots[].visual`，收集非空 visual 的 shot
- [ ] 用 ffmpeg overlay 将图片叠加到对应时间段
- [ ] 消除 `ffmpeg_assembler.py:321-324` 的 no-op 循环

#### 4C：清理死代码

- [ ] 移除 LLM Planner 旧版代码（`_convert()`、`LlmShot`、`LlmScene`），迁移 11 个旧测试
- [ ] 评估 Adapter 层（`adapter_impl.py`）：如近期不用 CLI/HTTP 工具，删除及对应测试

**验收标准**：
- 229 个现有测试全通过（或等量替换）
- `--planner rule` 输出与重构前完全一致

---

### Phase 5：多视觉类型支持

目标：实现 Pexels Image Tool，支持图文混合视频。

#### 5A：Pexels Image Tool
- [ ] 实现 `PexelsImageTool`（`tool_type="image"`, `provider_name="pexels"`）
- [ ] 输入 `{query, source, orientation}` → 输出 `{path, width, height, source_url, cache_key}`
- [ ] 使用 ToolCache 统一缓存
- [ ] 注册到 ToolRegistry，config 支持 Pexels API Key
- [ ] 单元测试

#### 5B：Ken Burns 动效
- [ ] Assembler 对图片 overlay 应用 ffmpeg `zoompan` 滤镜
- [ ] 配置化：zoom 方向、速度、持续时间

#### 5C：端到端验证
- [ ] LLM Planner 生成包含 `stock_image` scene 的 plan → Pipeline 调度 Image Tool → Assembler 叠加图片
- [ ] 回归测试：全 text_only 的输出与 Phase 4 行为一致

---

### Phase 6：渲染重构

- [ ] Manim 迁移到 Tool 接口（替代 subprocess 调用）
- [ ] Renderer 感知 Shot 粒度（按 Shot 分组渲染，而非逐 segment）
- [ ] 时长对齐：传递 `target_duration` 到渲染器，替代 `self.wait(2)` 硬编码
- [ ] 视觉效果抽为可复用 Manim 模板（标题卡、文字显示、动画点、章节标题）
- [ ] Scene Registry 元数据写入 plan.json

---

### 远期规划

- Remotion 程序化视频（数据可视化、片头片尾）
- AI 视频生成（Runway / Kling / Sora）
- AI 图片生成（DALL-E / Flux）
- AI 作曲 / 环境音效生成
- 世界模型驱动视频
