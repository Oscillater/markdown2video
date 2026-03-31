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

### 新版 Pipeline（推荐）

在项目根目录运行：

```bash
cd D:\Project\markdown2video
python -m md2video anim/example.md -o artifacts/output.mp4
```

可选参数：

```
--voice VOICE       TTS 语音 (默认: zh-CN-YunxiNeural)
--speed SPEED       TTS 语速 (默认: 1.0)
--artifacts DIR     产物目录 (默认: artifacts/)
-o, --output FILE   输出文件路径 (默认: output.mp4)
```

### 旧版（Legacy）

```bash
cd anim
manim -pql main.py Demo
```

## 两种方式对比

| | 新版 (`python -m md2video`) | 旧版 (`manim -pql main.py Demo`) |
|--|--|--|
| 架构 | 模块化，Manifest 驱动 | 单体，耦合度高 |
| TTS | 预生成，独立于 Manim | Manim 内实时生成 |
| 可扩展 | 工具可替换，Planner 可插拔 | 硬编码 |
| 代码位置 | `md2video/` | `anim/` |

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
md2video/              # 新版模块化代码
    manifest/          # Plan/Result Manifest 数据模型
    parser/            # Markdown 解析
    tools/tts/         # TTS 工具 (edge-tts)
    tools/render/      # Manim 渲染 + CachedVoiceService
    assembler/         # FFmpeg 合成
    core/              # Pipeline 编排 + Planner
    cli.py             # 命令行入口
    config.py          # 配置常量
anim/                  # 旧版代码（保留作为参考）
artifacts/             # 生成的中间产物（gitignored）
changelog/             # 变更日志
```

## Contributing

欢迎提交 Issue 或 Pull Request。
