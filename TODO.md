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
│               ↑                         │
│          Manifest（中间状态）            │
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

将解析后的文本切分为**语义段（Segment）**，每个 Segment 是最小的时间单元。

默认行为：基于标点和长度的规则分句（当前 `md_parser.py` 中 `custom_sentence_split` 的逻辑）。

可选增强：将 Segment 列表交给 Planner 做合并/拆分建议，但框架保留最终裁量权。

---

### 3.3 Manifest（清单）

**框架最核心的中间数据结构。**

Manifest 分为两个阶段：

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
      "visual": {
        "path": "./artifacts/seg_001_bg.jpg",
        "width": 1080,
        "height": 1920,
        "source": "pexels"
      },
      "start": 0.0,
      "end": 4.2
    }
  ]
}
```

---

### 3.4 Planner（规划器）

**归属：可替换的处理节点，非必需。**

Planner 的职责：接收 Segment 列表，为每个 Segment 补全视觉方案。

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

输入（单个 Segment 的上下文）：
```json
{
  "text": "...",
  "section": "...",
  "prev_visual_type": "...",
  "available_types": ["text_only", "stock_image", "stock_video", "manim_template"]
}
```

输出（必须严格符合 schema）：
```json
{
  "visual_type": "stock_image",
  "params": {
    "query": "AI technology city"
  },
  "fallback": "text_only",
  "confidence": 0.85
}
```

**两种 Planner 的输出 schema 完全相同。框架只消费 schema，不关心谁生成的。**

---

### 3.5 Tools（工具层）

工具是框架的外部执行器。每个工具契约：**固定输入 → 执行 → 固定输出 + 产物文件**。

工具不持有全局状态，不做拼接，不做编排。

#### TTS Tool

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

#### Image Tool

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

#### Render Tool（视频片段渲染）

当前阶段使用 Manim 模板渲染，输入为模板名 + 参数，而非自由代码：

输入：
```json
{
  "template": "title_card",
  "params": {
    "title": "神经网络",
    "subtitle": "像大脑一样思考",
    "duration": 4.2
  }
}
```

输出：
```json
{
  "path": "./artifacts/xxx.mp4",
  "duration": 4.2,
  "width": 480,
  "height": 854,
  "cache_key": "ghi789"
}
```

---

### 3.6 Assembler（合成器）

**归属：框架内建，使用 FFmpeg 作为唯一合成引擎。**

消费 Result Manifest，执行：

1. 按时间轴拼接所有视频/图片片段
2. 混入 TTS 音轨
3. 叠加背景音乐（含音量控制、淡入淡出）
4. 叠加图片 Overlay（含时间段控制）
5. 可选：烧录字幕
6. 导出最终 MP4

Assembler 不关心片段从哪里来，只消费标准化产物。

---

## 4. Fallback 策略

框架内建三级 Fallback，每个工具调用都可配置：

| 级别 | 策略 | 示例 |
|------|------|------|
| L1 | 同 Provider 重试 | edge-tts 超时，重试一次 |
| L2 | 换 Provider | pexels 无结果，换 pixabay |
| L3 | 降级输出 | 图片搜索失败，改用纯文字动画片段 |

Manifest 中每个 segment 的 `fallback` 字段由 Planner 填写，框架执行。

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

| 当前文件 | 对应新模块 |
|----------|-----------|
| `md_parser.py` | Parser + Segmenter（保留，小幅调整） |
| `main.py` 中的 TTS 逻辑 | TTS Tool |
| `main.py` 中的 Manim Scene | Render Tool（模板化） |
| `main.py` 中的 timeline 生成 | Framework Core（Executor 填充 Result Manifest） |
| `insert_media.py` | Assembler（保留核心，接入标准 Manifest） |
| `edge_tts_voice.py` | TTS Tool 的 edge-tts provider 实现 |

`main.py` 当前是最强耦合点，后续拆解优先级最高。

---

## 8. 开发路线图

### Phase 1：重构现有代码，建立分层边界

- [x] 定义 Manifest schema（Plan + Result）
- [x] 将 `md_parser.py` 的输出对齐到 Plan Manifest
- [x] 将 TTS 逻辑抽离为独立的 TTS Tool，返回标准 schema
- [x] 将 `insert_media.py` 改为消费 Result Manifest 的 Assembler
- [x] 框架 Core 串联上述模块，替代现有 `main.py` 的编排逻辑

**产出：能跑通的 Manifest 驱动流水线，功能与现在等价。**

### Phase 2：扩展工具，增加 Image Tool

- [ ] 实现 Rule Planner（基于关键词规则）
- [ ] 接入 Pexels Image Tool
- [ ] 框架支持"图片片段"类型（Pan/Zoom 动效）
- [ ] 实现 L1/L2/L3 Fallback 框架

**产出：支持图文混合的视频生成，不依赖 LLM。**

### Phase 3：接入 LLM Planner（可选）

- [ ] 实现 LLM Planner 接口
- [ ] 框架支持 `config.yaml` 中切换 Rule / LLM Planner
- [ ] LLM Planner 输出校验（强 schema 验证）
- [ ] 用户 API Key 配置文档

**产出：LLM 可选的语义增强，不影响无 key 用户正常使用。**

### Phase 4：Manim 模板库 + 稳定性

- [ ] 建立标准 Manim 模板集（标题卡、列表、流程图、关键词高亮等）
- [ ] Render Tool 支持按模板名调用
- [ ] 缓存层完整实现
- [x] 单元测试覆盖 Parser、Planner、各 Tool

**产出：稳定可复用的视频模板体系。**

---

## 9. 关键设计原则

1. **Markdown 显式指令最高优先级**，框架规则其次，Planner 补全最后。
2. **框架不依赖 Agent 稳定运行**，所有 Planner 节点都有规则兜底。
3. **工具只做一件事**，不持有状态，不做全局编排。
4. **合成由 FFmpeg 统一执行**，工具只产出原始素材。
5. **Manifest 是唯一数据流**，不允许工具之间直接通信。