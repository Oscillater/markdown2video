# markdown2video

将 Markdown 文本转换为带语音、背景音乐和图片叠加的动画视频。

## 环境要求

- **Python 3.11+**
- **ffmpeg** (需在 PATH 中)
- **sox** (可选，用于高级音频处理)

Python 依赖：

```
manim >= 0.19.0
manim-voiceover
edge-tts
pydantic >= 2.0
typing_extensions >= 4.15.0
pydantic-ai >= 1.76.0
python-dotenv >= 1.0.0
Pillow
requests
```

## 安装

```bash
pip install manim manim-voiceover edge-tts pydantic pydantic-ai python-dotenv Pillow requests
```

如果 manim 导入报错 `cannot import name 'TypeIs'`，需要升级 typing_extensions：

```bash
pip install --upgrade typing_extensions
```

确保 ffmpeg 在 PATH 中（Windows）：

```powershell
$env:PATH += ";D:\ffmpeg\bin"
```

## 使用方法

在项目根目录运行：

```bash
cd D:\Project\markdown2video
python -m md2video example/example.md -o artifacts/output.mp4
```

也可以直接执行 PlanManifest：
```bash
python -m md2video --plan path/to/plan.json -o artifacts/output.mp4
```

可选参数：

```
--voice VOICE       TTS 语音 (默认: zh-CN-YunxiNeural)
--speed SPEED       TTS 语速 (默认: 1.0)
--artifacts DIR     产物目录 (默认: artifacts/)
--planner TYPE      Planner 类型: rule（默认）或 llm
--plan FILE         PlanManifest JSON 输入（跳过 Markdown parser/planner）
-o, --output FILE   输出文件路径 (默认: output.mp4)
```

### LLM Planner

默认使用 Rule Planner（纯规则分组，无需 API Key）。如需 LLM 语义分组：

1. 复制 `.env.example` 为 `.env`，填入配置：

```env
MD2VIDEO_PLANNER=llm
OPENAI_API_KEY=sk-your-key-here
MD2VIDEO_LLM_MODEL=openai:gpt-4o
# MD2VIDEO_LLM_BASE_URL=https://api.openai.com/v1
```

2. 运行：

```bash
python -m md2video example/example.md -o artifacts/output.mp4 --planner llm
```

**支持的模型格式**（通过 `MD2VIDEO_LLM_MODEL` 配置）：

| 格式 | 示例 | 说明 |
|------|------|------|
| OpenAI | `openai:gpt-4o` | 官方 OpenAI API |
| OpenAI 兼容 | `openai:gpt-4o` + 设 `MD2VIDEO_LLM_BASE_URL` | 中转站、本地部署等 |

LLM 调用失败时会自动 fallback 到 Rule Planner，不影响正常使用。

## 架构

```
Markdown → Parser/Planner → Plan Manifest → Execution Assets → Manim Renderer → Timeline → FFmpeg Assembler → Final Result → MP4
```

核心概念：

- **Segment**：内容原子，通常是一句话或一个标题；持有朗读、显示、动画和 `target_duration` 等计划意图
- **Shot**：最小连续视觉执行单元，由有序 Segment 和 marker/media/visual cue 组成，并保持一段连续视觉状态
- **Scene**：视觉策略组，共享素材策略、layout/template 和风格决策

数据流：

1. **Parser** 将 Markdown 解析为 Segment 列表
2. **Planner** 将 Segment 分组为 Shot，将 marker 降级为 shot cue，并为 Scene 分配视觉和 layout 策略
3. **PlanManifest** 保存计划和目标约束，不保存执行产物
4. **ExecutionAssets** 记录 TTS 音频、本地图片或 Pexels 图片等素材事实
5. **Manim Renderer** 渲染基础视频，并输出真实时间事实 `timeline.json`
6. **FFmpeg Assembler** 根据真实 timeline 拼接视频、混入语音、叠加音乐和图片
7. **FinalResultManifest** 在 assemble 完成后写出最终 MP4、used assets、warnings 和 artifact index

### Planner

提供两种可互换的 Planner 实现，输入输出格式完全相同：

- **Rule Planner**（默认）：基于规则的分组，无需 API Key，稳定可预测
- **LLM Planner**：两阶段语义规划
  - 全局定调：输入完整 Markdown，LLM 定义 3~5 个 Scene 视觉模板
  - 局部分镜：按章节分块，每块独立调 LLM 映射 Shot 到 Scene 模板
  - 框架重组：合并映射、校验完整性、拆分显式指令
  - 失败时自动 fallback 到 Rule Planner

## Markdown 语法

### 标题（每个文件只能用一次）

```markdown
# 主标题
## 副标题
```

### 小节标题

```markdown
### 第一节
### 第二节
```

每个 `###` 标题会在视频左侧显示，用于划分内容段落。

### 正文

标题下方的文字为正文内容，会配以语音朗读。

### 附录

```markdown
---
下面是附录内容
```

`---` 分隔线之后的内容为附录。附录中的正文会朗读，但音乐默认全音量播放。

### 背景音乐

在文件顶部声明音乐资源，然后在正文中标记播放区间：

```markdown
[music:name="bgm",src="./music.mp3"]

### 第一节
正文内容
[music_start bgm]
这段文字播放时会有背景音乐
[music_end bgm]
```

### 图片叠加

```markdown
[image:name="logo",src="./logo.png"]

[image_start logo]
这段文字播放时会有图片显示
[image_end logo]
```

## 项目结构

```
md2video/              # 核心代码
    manifest/          # Plan/Result Manifest 数据模型 (含 Segment + Shot + Scene)
    parser/            # Markdown 解析
    tools/tts/         # TTS 工具 (edge-tts)
    tools/render/      # Manim 渲染 + CachedVoiceService
    tools/             # Tool 基础设施 (Protocol, Registry, Cache)
    assembler/         # FFmpeg 合成
    core/              # Pipeline 编排
        planner/       # Planner (Rule + LLM 两阶段)
    cli.py             # 命令行入口
    config.py          # 配置常量
example/               # 示例 Markdown
tests/                 # 单元测试
artifacts/             # 生成的中间产物（gitignored）
changelog/             # 变更日志
```

## Contributing

欢迎提交 Issue 或 Pull Request。
