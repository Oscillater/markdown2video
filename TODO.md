这份文档基于我们需要实现的 **“Markdown 驱动的多模态视频生成 Agent”** 方案整理而成。

它将作为一个技术蓝图（Blueprint），指导从 MVP 到最终成品的开发。

---

# 项目设计文档：Markdown 驱动的多模态视频 Agent
**Project Name:** Auto-Director (暂定)
**Version:** 0.1 (Draft)

## 1. 核心愿景 (Core Vision)
构建一个**“文本驱动 (Text-Based)”**的自动化视频生产系统。
系统以 Markdown 脚本为绝对核心，通过 TTS（语音合成）确定时间轴，利用 LLM（大模型）作为“导演”进行语义分析，动态调度 Manim（数学/逻辑渲染）、网络素材搜索、AIGC 生成等多种工具，最终合成高质量的科普/解说视频。

**核心哲学：**
*   **Timeline is Truth:** 视频的时间轴完全由文本朗读时长决定。
*   **Everything is an Object:** 所有的视频片段（无论是代码画的、搜来的、拍的）都是一个对象（Class Instance）。
*   **Manifest First:** 先生成结构化的“拍摄清单 (JSON)”，再进行并行渲染。

---

## 2. 系统架构 (Architecture)

系统分为四个主要阶段：**解析与对齐 (Pre-Processing)** -> **导演决策 (Director Agent)** -> **多态渲染 (Polymorphic Rendering)** -> **合成 (Assembly)**。

### 2.1 数据流图
```mermaid
graph TD
    User[用户 Markdown] --> Parser[语义分段器]
    Parser --> TTS[TTS 引擎]
    TTS -->|音频 + 时长| Manifest_Init[初始清单 JSON]
    
    Manifest_Init --> Director[Director Agent (LLM)]
    Director -->|补充视觉参数| Manifest_Final[最终拍摄清单 JSON]
    
    Manifest_Final --> Dispatcher[调度工厂]
    
    Dispatcher -->|Type: Manim| WorkerA[Manim 渲染器]
    Dispatcher -->|Type: Stock| WorkerB[素材搜刮器]
    Dispatcher -->|Type: AIGC| WorkerC[AI 生图/视频]
    
    WorkerA & WorkerB & WorkerC --> Clips[标准化视频片段 Pool]
    Clips --> Editor[FFmpeg 合成器]
    Editor --> FinalVideo[最终成片]
```

---

## 3. 核心模块详解

### 3.1 阶段一：预处理 (Pre-Processing)
**目标**：将非结构化的 Markdown 转化为带有时长信息的结构化数据。

1.  **Semantic Segmenter (语义分切)**
    *   利用 LLM 将长文本按“视觉逻辑”切分为短句列表。
    *   *规则*：每段文本对应一个独立的画面；避免一句话过长（>20字）或过短。
2.  **Audio Aligner (音频对齐)**
    *   调用 TTS API (Edge-TTS / OpenAI / Azure)。
    *   生成 `.mp3` 文件。
    *   获取精确的 `duration` (浮点数，如 3.45s)。

### 3.2 阶段二：导演决策 (The Director Agent)
**目标**：完善清单，决定“每一秒看什么”。

*   **输入**：包含文本和时长的 JSON。
*   **Agent 任务**：
    1.  理解文本含义。
    2.  选择最合适的渲染类（Class）。
    3.  生成该类所需的参数（Parameters）。
*   **数据结构 (The Manifest JSON)**：
    这是系统最重要的中间件文件。
    ```json
    {
      "timeline": [
        {
          "id": 1,
          "text": "神经网络就像一个复杂的大脑",
          "duration": 4.2,
          "audio_path": "./tmp/audio_1.mp3",
          "visual_type": "manim",
          "visual_params": {
            "intent": "draw_neural_network",
            "style": "abstract",
            "highlight_nodes": true
          }
        },
        {
          "id": 2,
          "text": "在现实生活中，它无处不在",
          "duration": 3.0,
          "audio_path": "./tmp/audio_2.mp3",
          "visual_type": "stock",
          "visual_params": {
            "search_query": "AI city technology",
            "source": "pexels"
          }
        }
      ]
    }
    ```

### 3.3 阶段三：多态渲染工厂 (The Factory)
**目标**：执行清单，输出标准化的 MP4 片段。

基于 **OOP (面向对象)** 设计，定义基类 `VisualSegment`：

```python
class VisualSegment(ABC):
    def generate(self) -> str:
        """返回生成的 .mp4 文件路径"""
        pass
```

#### 子类实现：
1.  **ManimSegment (逻辑可视化)**
    *   **核心逻辑**：Prompt Engineering -> 生成 Python 代码 -> 沙箱执行 -> 错误捕获与重试 (Self-Healing)。
    *   **关键点**：必须将 `duration` 传入代码，控制 `self.wait()` 或 `run_time`。
2.  **StockSegment (现实素材)**
    *   **核心逻辑**：调用 Pexels/Unsplash API -> 下载 -> FFmpeg 裁剪时长 -> 添加 Zoom/Pan 动效（防止静图枯燥）。
3.  **AIGCSegment (生成式素材)**
    *   **核心逻辑**：调用 DALL-E 3 -> 图像转视频 (SVD/Runway) 或 简单运镜。

### 3.4 阶段四：后期合成 (Assembly)
**目标**：将碎片拼接成完整视频。

*   **工具**：`MoviePy` 或 直接调用 `FFmpeg` 命令行。
*   **功能**：
    *   **Concatenate**：按顺序拼接所有片段。
    *   **Audio Mix**：将 TTS 音轨与背景音乐 (BGM) 混合。
    *   **Subtitles**：(可选) 根据时间轴自动烧录字幕。
    *   **Transitions**：片段之间添加 `CrossFade` (叠化) 以减少割裂感。

---

## 4. 技术栈推荐 (Tech Stack)

| 模块           | 推荐技术/库                | 说明                        |
| :------------- | :------------------------- | :-------------------------- |
| **语言**       | Python 3.10+               | 胶水语言，Manim 原生支持    |
| **Agent 框架** | **LangGraph** / LangChain  | 用于构建工作流和状态管理    |
| **渲染引擎**   | **Manim Community**        | 数学/逻辑动画核心           |
| **视频处理**   | **MoviePy** / FFmpeg       | 剪辑、拼接、特效            |
| **LLM**        | GPT-4o / Claude 3.5 Sonnet | 代码生成能力强，视觉理解好  |
| **素材 API**   | Pexels API / Pixabay       | 免费高清无版权素材          |
| **Web 框架**   | FastAPI                    | (后期) 如果要做成 SaaS 服务 |

---

## 5. 开发路线图 (Roadmap)

### Phase 1: MVP (最小可行性产品) - **Text-to-Manim**
*   **目标**：跑通 Markdown -> TTS -> Manim 渲染 -> 视频拼接。
*   **限制**：只支持 Manim 一种类型，不进行复杂的 Agent 决策，只做简单的模板填空。
*   **产出**：一个 Python 脚本，输入 Markdown，输出 MP4。

### Phase 2: The Agent (引入导演) - **Semantic Dispatch**
*   **目标**：引入 `VisualSegment` 基类和 `StockSegment`。
*   **功能**：Agent 能够判断何时用 Manim，何时用搜图。实现 Manifest JSON 的生成逻辑。
*   **产出**：支持混合剪辑的命令行工具。

### Phase 3: Enhancement (增强与稳定性) - **Self-Healing & Style**
*   **目标**：解决 Manim 代码报错痛点，增加自动重试机制；优化 FFmpeg 转场效果。
*   **功能**：增加 Manim 代码纠错 Loop；增加图片转视频的运镜效果。

### Phase 4: Object-Oriented Expansion (无限扩展)
*   **目标**：接入更多类型的 Segment。
*   **功能**：接入 AIGC 生图工具；接入物理设备接口（如有）；开发 Web 前端界面。

---

## 6. 关键注意事项 (Notes)

1.  **沙箱安全**：Manim 需要执行 LLM 生成的 Python 代码，务必在 Docker 容器或受限环境中运行 `exec()`，防止文件系统被误删。
2.  **时长强一致性**：渲染器生成的视频时长必须 >= 音频时长。如果渲染短了，画面会黑屏；如果渲染长了，声音会对不上。建议渲染时长略长于音频，后期剪辑时截断。
3.  **Prompt 技巧**：在让 Agent 生成 Manim 代码时，要强制它使用相对坐标（`next_to`）而不是绝对坐标，以适应不同长度的文本布局。