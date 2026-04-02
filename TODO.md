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
│          (语义分组+视觉决策)             │
│               ↑                         │
│          Manifest（中间状态）            │
│      ┌─────┴─────┐                      │
│   Segments    Scenes                    │  双层数据模型
└────────────────────┬────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│              Tools（工具层）              │
│                                         │
│   TTS Tool │ Image Tool │ Render Tool   │  执行层
└────────────────────┬────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│            Assembler（合成层）           │  输出层
│         FFmpeg 统一拼接，输出 MP4        │
└─────────────────────────────────────────┘
```

**核心变化：引入 Scene（镜头）概念。**

- **Segment** 是最小时间单元（一句话），保持不变
- **Scene** 是语义单元，由 Planner 将多个 Segment 分组而成，共享同一个视觉方案
- Planner 同时负责两件事：① 语义分组（哪些句子属于同一个镜头）② 视觉决策（这个镜头用什么视觉呈现）

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

### 3.2.1 Scene（镜头）— 由 Planner 产出

**归属：Planner 的输出，不属于 Parser。**

Scene 是**语义级别的分组单元**，由 Planner 将多个 Segment 合并而成。同一个 Scene 下的所有 Segment 共享同一个视觉方案（visual_type + visual_params）。

**为什么需要 Scene：**
- 一段科普视频讲"神经网络"，可能包含 5-6 个句子。这些句子语义相关，应该共享同一张背景图、同一种动画风格。
- 如果逐 sentence 决定视觉，会导致频繁切换、视觉不连贯。
- Scene 让 Planner 能以"镜头"为单位思考：这个镜头讲什么、配什么图、用什么动画。

**Scene 与 Segment 的关系：**
- 一个 Scene 包含 1~N 个 Segment
- 一个 Segment 只属于一个 Scene
- Segment 是 TTS 的单位，Scene 是视觉的单位
- 时间轴上，Scene 的 start/end 由其包含的所有 Segment 的音频时长累加得出

**示例：**
```
Segment: "神经网络就像一个复杂的大脑"         ┐
Segment: "它由大量的人工神经元组成"           ├─ Scene 1: visual_type="stock_image"
Segment: "每个神经元与其他神经元相连"         ┘   visual_params={"query": "neural network"}

Segment: "深度学习是神经网络的一种"           ┐
Segment: "它在图像识别方面表现出色"           ┘─ Scene 2: visual_type="text_only"
```

---

### 3.3 Manifest（清单）

**框架最核心的中间数据结构。**

Manifest 分为两个阶段，每个阶段都有 Segment 层和 Scene 层：

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
        "query": "neural network abstract",
        "fallback": "text_only"
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

#### Plan Manifest 中的 Scene

Scene 由 Planner 生成分组后填入 Plan Manifest：

```json
{
  "scenes": [
    {
      "id": "scene_001",
      "visual_type": "stock_image",
      "visual_params": {
        "query": "neural network abstract",
        "fallback": "text_only"
      },
      "segment_ids": ["seg_001", "seg_002", "seg_003"],
      "section_context": "什么是神经网络"
    },
    {
      "id": "scene_002",
      "visual_type": "text_only",
      "visual_params": {},
      "segment_ids": ["seg_004", "seg_005"],
      "section_context": "什么是神经网络"
    }
  ]
}
```

**Scene 与 Segment 的双向关联：**
- `Scene.segment_ids` → 引用属于该 Scene 的 Segment ID 列表
- Segment 上的 `visual_type` / `visual_params` 由所属 Scene 决定（冗余存储，方便渲染时直接读取）

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

注：Segment 的视觉信息不再单独记录（视觉由 Scene 统一管理）。

#### Result Manifest 中的 Scene

Scene 的结果记录该镜头的整体时间范围和视觉产物：

```json
{
  "scenes": [
    {
      "id": "scene_001",
      "segment_ids": ["seg_001", "seg_002", "seg_003"],
      "start": 0.0,
      "end": 12.5,
      "visual": {
        "path": "./artifacts/scene_001_bg.jpg",
        "width": 1080,
        "height": 1920,
        "source": "pexels"
      }
    }
  ]
}
```

`SceneResult.start/end` 由其所含 Segment 的音频时长累加得出。`visual` 字段记录该 Scene 的视觉产物（图片、视频等），由 Image Tool 或 Render Tool 填充。

---

### 3.4 Planner（规划器）

**归属：可替换的处理节点，非必需。**

Planner 的职责：接收 Segment 列表，完成两件事：
1. **语义分组**：将 Segment 合并为 Scene（镜头）
2. **视觉决策**：为每个 Scene 补全 visual_type 和 visual_params

**Planner 是一个接口，有两种实现：**

#### A. Rule Planner（规则规划器）
纯代码逻辑，基于关键词、段落长度、上下文规则来决定 `visual_type` 和参数。
- 稳定、可预测、无需 API Key
- 推荐作为默认和 fallback

#### B. LLM Planner（语言模型规划器）
调用外部 LLM API，做语义理解后返回结构化决策。
- 需要用户配置 API Key
- 只用于语义判断，**不负责生成代码或直接操作文件**
- 输出必须符合 Planner Schema（见下文），框架做强校验

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
  "available_visual_types": ["text_only", "stock_image", "stock_video", "manim_template"]
}
```

输出（必须严格符合 schema — 包含 Scene 分组 + 视觉决策）：
```json
{
  "scenes": [
    {
      "id": "scene_001",
      "visual_type": "stock_image",
      "visual_params": {
        "query": "neural network abstract",
        "fallback": "text_only"
      },
      "segment_ids": ["seg_001", "seg_002"],
      "confidence": 0.85
    },
    {
      "id": "scene_002",
      "visual_type": "text_only",
      "visual_params": {},
      "segment_ids": ["seg_003"],
      "confidence": 0.95
    }
  ]
}
```

**两种 Planner 的输出 schema 完全相同。框架只消费 schema，不关心谁生成的。**

---

### 3.5 Tools（工具层）

工具是框架的外部执行器。每个工具契约：**固定输入 → 执行 → 固定输出 + 产物文件**。

工具不持有全局状态，不做拼接，不做编排。

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
  "sample_rate": 24000,
  "provider": "edge-tts",
  "cache_key": "abc123"
}
```

**未来可扩展：**
- Azure TTS / Google TTS / ChatTTS 等其他 TTS Provider
- 音效生成工具（如 AI 环境音效生成）
- 背景音乐生成工具（AI 作曲）

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

**未来可扩展：**
- AI 图片生成（Midjourney / DALL-E / Flux 等风格的 prompt 生成 + API 调用）
- 图片后处理（风格迁移、抠图、调色）

#### Video Tools（视频工具）

处理视频片段的生成和渲染。

**Manim Render Tool（当前）**

按 Scene 粒度驱动，每个 Scene 决定一组 Segment 的视觉呈现方式：

输入（一个 Scene + 其包含的 Segment 结果）：
```json
{
  "scene": {
    "id": "scene_001",
    "visual_type": "text_only",
    "visual_params": {}
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

**未来可扩展：**
- AI 视频生成（如 Runway / Kling / Sora 等生成式 AI 视频，由 Scene 的 visual_params 驱动 prompt）
- Remotion 程序化视频（通过 [Remotion](https://github.com/remotion-dev/remotion) 生成特定风格的动画片段，如数据可视化、片头片尾）
- 世界模型驱动视频（如操控机械臂等物理世界模型生成特定动作的视频片段）
- Manim 模板渲染（将当前 construct() 方法中的效果拆为可复用模板：标题卡、流程图、关键词高亮等）

---

### 3.6 Assembler（合成器）

**归属：框架内建，使用 FFmpeg 作为唯一合成引擎。**

消费 Result Manifest（Segment + Scene），执行：

1. 按时间轴拼接所有 Scene 对应的视频片段
2. 混入 TTS 音轨
3. 叠加背景音乐（含音量控制、淡入淡出）
4. 叠加图片 Overlay（基于 Scene 的 visual 结果，含 Pan/Zoom 动效）
5. 可选：烧录字幕
6. 导出最终 MP4

Assembler 不关心片段从哪里来，只消费标准化产物。

---

### 3.7 时长对齐（Duration Alignment）

**这是框架必须解决的核心问题之一。**

一个 Scene 的最终时长由多个来源决定，它们往往不一致：

| 来源 | 产出 | 特点 |
|------|------|------|
| TTS（Audio Tool） | Segment 级别的音频时长 | 每句话一个文件，时长由语速+文本长度决定 |
| Render（Video Tool） | Scene 级别的视频时长 | 可能是 Manim 动画时长、Remotion 渲染时长、AI 视频固定时长 |
| Image（Image Tool） | 无时长 | 静态图片需要 Framework 决定展示多久 |
| AI 视频生成 | 固定时长（如 4s/8s/16s） | 与 TTS 时长往往不匹配 |

**对齐策略：以 TTS 时长为主轴，其他工具适配。**

1. **TTS 时长 = 主时间轴**：每个 Segment 的 TTS 音频时长决定该 Segment 的 start/end，累加得出 Scene 的总时长。这是不可变的基础时间线。

2. **Render Tool 适配**：Manim/Remotion 等渲染工具需要接收目标时长，渲染出与 TTS 时长匹配的视频。例如 Manim 中通过 `self.wait()` 填充时间。

3. **Image Tool 适配**：静态图片无固有时长，由 Scene 时长决定展示时长。Assembler 通过 ffmpeg 的 `-t` 参数控制图片 overlay 的持续时间。

4. **AI 视频生成适配**：AI 生成的视频有固定时长（如 4s），可能短于或长于对应 Scene 的 TTS 时长。Framework 需要处理：
   - **AI 视频较短**：循环播放、慢放（`setpts=2*PTS`）、或截取最后帧静帧填充
   - **AI 视频较长**：裁剪（`-t` 参数）、加速、或只取关键片段
   - **永远不截断 TTS**：语音内容必须完整播放，视觉可以适配

5. **时长差异的阈值警告**：当 AI 生成视频与目标时长差异超过阈值（如 >50%），Framework 记录 warning 但不中断流程。

**一句话：TTS 说多久，视频就多久。视觉素材去适配语音，而不是反过来。**

---

## 4. Fallback 策略

框架内建三级 Fallback，每个工具调用都可配置：

| 级别 | 策略 | 示例 |
|------|------|------|
| L1 | 同 Provider 重试 | edge-tts 超时，重试一次 |
| L2 | 换 Provider | pexels 无结果，换 pixabay |
| L3 | 降级输出 | 图片搜索失败，改用纯文字动画片段 |

Manifest 中每个 Scene 的 `visual_params.fallback` 字段由 Planner 填写，框架执行。

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
providers:
  tts:
    default: edge-tts          # 无需 key
    fallback: azure-tts
    azure-tts:
      api_key: ${AZURE_TTS_KEY}

  image:
    default: pexels
    pexels:
      api_key: ${PEXELS_API_KEY}

  planner:
    default: rule              # 默认使用规则，不需要 key
    llm:
      provider: openai
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
```

框架通过配置文件决定调用哪个 provider，不在代码中硬编码任何 key。

---

## 7. 当前代码与新架构的对应关系

| 当前文件 | 对应新模块 | Phase |
|----------|-----------|-------|
| `md_parser.py` | Parser + Segmenter（保留，小幅调整） | ✅ 1 |
| `schema.py` | Manifest Schema（需新增 ScenePlan/SceneResult） | 2A |
| `rule_planner.py` | Rule Planner（需实现场景分组逻辑） | 2A |
| `pipeline.py` | Pipeline 编排器（需适配 Scene 粒度） | 2A |
| `manim_renderer.py` | Render Tool（需按 Scene 循环渲染） | 2A |
| `ffmpeg_assembler.py` | Assembler（需按 Scene 视觉方案叠加） | 2A/2B |
| `edge_tts.py` | TTS Tool（已完成，不需改动） | ✅ 1 |
| （新增） | Image Tool（Pexels API） | 2B |
| （新增） | Fallback 框架 | 2B |

`main.py` 当前是最强耦合点，后续拆解优先级最高。

---

## 8. 开发路线图

### Phase 1：重构现有代码，建立分层边界 ✅

- [x] 定义 Manifest schema（Plan + Result）
- [x] 将 `md_parser.py` 的输出对齐到 Plan Manifest
- [x] 将 TTS 逻辑抽离为独立的 TTS Tool，返回标准 schema
- [x] 将 `insert_media.py` 改为消费 Result Manifest 的 Assembler
- [x] 框架 Core 串联上述模块，替代现有 `main.py` 的编排逻辑

**产出：能跑通的 Manifest 驱动流水线，功能与现在等价。**

### Phase 2A：Scene 架构 + Rule Planner

- [x] 引入 ScenePlan / SceneResult 数据模型（schema.py）
- [x] Planner 输出从"逐 segment 设 visual_type"改为"分组 segments 为 scenes"
- [x] Rule Planner 实现基于规则的场景分组（关键词 + 上下文 + 长度判断）
- [x] Pipeline 适配 Scene 粒度：Parser → Planner(分组) → TTS(逐segment) → Render(逐scene) → Assemble
- [x] Renderer 适配 Scene 粒度：按 Scene 循环渲染，而非逐 segment
- [x] Assembler 适配 Scene 粒度：按 Scene 的 visual 方案叠加图片/动效
- [x] 修复 result.json 写盘顺序导致 scenes 为空的 bug
- [x] 补充写盘→读回集成测试（test_write_then_read_preserves_scenes）

**产出：引入 Scene（镜头）概念，Planner 能将语义相关的句子分组为统一视觉的镜头。**

### Phase 2B：图片工具 + 视觉扩展

- [ ] 实现 Pexels Image Tool（按 Scene 的 visual_params 搜索图片）
- [ ] 实现 Pan/Zoom 动效（ffmpeg zoompan 滤镜，让静态图片有 Ken Burns 效果）
- [ ] 实现 L1/L2/L3 Fallback 框架（同 Provider 重试 → 换 Provider → 降级为 text_only）
- [ ] 缓存层完善（图片按 query+source 缓存）

**产出：支持图文混合的视频生成，带 Pan/Zoom 动效和容错，不依赖 LLM。**

### Phase 2C：工具扩展预留（架构层面）

- [ ] 定义 Audio / Image / Video 三类工具的统一接口基类
- [ ] 时长对齐机制：以 TTS 时长为主轴，Render/Image/AI Video 适配（见 3.7 节）
- [ ] 工具注册机制：新工具可通过配置注册，无需改动 Pipeline 核心代码
- [ ] visual_type 与工具的映射关系可配置化（如 `stock_image` → Pexels Tool，`ai_video` → Runway Tool）

**产出：架构层面支持未来接入任意工具，新增工具只需实现接口 + 注册，不改 Pipeline。**

注：以下工具为远期规划，Phase 2C 只做架构预留，不实现具体工具：
- AI 视频生成（Runway / Kling / Sora 等）
- Remotion 程序化视频（数据可视化、片头片尾等）
- 世界模型驱动视频（机械臂等物理模拟）
- AI 图片生成（Midjourney / DALL-E / Flux 风格）
- AI 作曲 / 环境音效生成

### Phase 3：接入 LLM Planner（可选）

- [ ] 实现 LLM Planner 接口（语义分组 + 视觉决策一体化）
- [ ] 框架支持 `config.yaml` 中切换 Rule / LLM Planner
- [ ] LLM Planner 输出校验（强 schema 验证）
- [ ] 用户 API Key 配置文档

**产出：LLM 可选的语义增强，不影响无 key 用户正常使用。**

### Phase 4：模板库 + 工具库重构

- [ ] 将现有 Renderer 中的视觉效果抽为可复用 Manim 模板：
  - 标题卡片（title_card）
  - 文字显示（text_display）
  - 动画点（animated_dots）
  - 章节标题堆叠（section_header_stack）
- [ ] 每个 Scene 的 visual_type 对应一个模板，Render Tool 按模板名 + 参数调用
- [ ] 建立标准 Manim 模板集（列表、流程图、关键词高亮等）
- [ ] 引入 Remotion 作为补充渲染引擎（程序化视频、数据可视化、片头片尾等复杂场景）
- [ ] 缓存层完整实现（同模板 + 同参数 → 复用渲染片段）
- [x] 单元测试覆盖 Parser、Planner、各 Tool

**产出：稳定可复用的视频模板体系，Render 不再是一个巨大的 construct() 方法。Manim + Remotion 双引擎，各取所长。**

---

## 9. 关键设计原则

1. **Markdown 显式指令最高优先级**，框架规则其次，Planner 补全最后。
2. **框架不依赖 Agent 稳定运行**，所有 Planner 节点都有规则兜底。
3. **工具只做一件事**，不持有状态，不做全局编排。
4. **合成由 FFmpeg 统一执行**，工具只产出原始素材。
5. **Manifest 是唯一数据流**，不允许工具之间直接通信。
6. **Segment 是 TTS 的单位，Scene 是视觉的单位**。两者各司其职，通过 Manifest 关联。