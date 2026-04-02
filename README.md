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
```

## 安装

```bash
pip install manim manim-voiceover edge-tts pydantic
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

可选参数：

```
--voice VOICE       TTS 语音 (默认: zh-CN-YunxiNeural)
--speed SPEED       TTS 语速 (默认: 1.0)
--artifacts DIR     产物目录 (默认: artifacts/)
-o, --output FILE   输出文件路径 (默认: output.mp4)
```

## 架构

```
Markdown → Parser → Plan Manifest → Planner → TTS → Result Manifest → Manim Renderer → FFmpeg Assembler → MP4
```

核心概念：

- **Segment**：最小时间单元（一句话），TTS 以 Segment 为单位合成语音
- **Scene**：语义单元，由 Planner 将多个 Segment 分组而成，共享同一个视觉方案

数据流：

1. **Parser** 将 Markdown 解析为 Segment 列表
2. **Planner** 将 Segment 语义分组为 Scene，并为每个 Scene 决定视觉方案
3. **TTS** 为每个 Segment 预生成语音
4. **Manim Renderer** 按 Scene 粒度渲染动画
5. **FFmpeg Assembler** 拼接视频、混入语音、叠加音乐和图片

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
    manifest/          # Plan/Result Manifest 数据模型 (含 Scene)
    parser/            # Markdown 解析
    tools/tts/         # TTS 工具 (edge-tts)
    tools/render/      # Manim 渲染 + CachedVoiceService
    assembler/         # FFmpeg 合成
    core/              # Pipeline 编排 + Planner
    cli.py             # 命令行入口
    config.py          # 配置常量
example/               # 示例 Markdown
tests/                 # 单元测试
artifacts/             # 生成的中间产物（gitignored）
changelog/             # 变更日志
```

## Contributing

欢迎提交 Issue 或 Pull Request。
