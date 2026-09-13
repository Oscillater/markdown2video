# 竞品调研与对标拆片（2026-09-13/14）

来源：GitHub 同类项目调研（四赛道）+ 知识区对标片拆解（文字资料级，非逐帧）。本文归档结论；执行项见 TODO。

## 一、GitHub 同类项目（四赛道）

| 赛道 | 代表 | 技术路线 | 与我们的关系 |
|---|---|---|---|
| 代码驱动视频引擎 | [Remotion](https://www.remotion.dev)、[Motion Canvas](https://motioncanvas.io)、[Revideo](https://github.com/redotvideo/revideo) | React/TS 逐帧渲染 | 基础设施（我们的 Remotion 后端架在其上），非竞品 |
| AI 口播短视频 | [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)（~56K★）、[ShortGPT](https://github.com/rayventura/shortgpt) | LLM 写脚本 → 素材库空镜 + TTS + 字幕 + BGM → MoviePy/FFmpeg 合成 | 需求侧验证（"文本进视频出"）；只会贴素材，做不了定制演算画面——我们的切入位 |
| Markdown 直转视频 | [markdown_video](https://github.com/Avik-creator/markdown_video)（CC BY-NC）| 自研 markdown 方言 → DOM → HTML2Canvas → FFmpeg.wasm 全浏览器 | 玩具级；无音频、时长手写；其 MCP 工具化思路值得学 |
| LLM→manim 讲解视频 | [TheoremExplainAgent](https://github.com/TIGER-AI-Lab/TheoremExplainAgent)（ACL 2025）、[Manimator](https://arxiv.org/html/2507.14306v1)、[Math-To-Manim](https://github.com/HarleyCoops/Math-To-Manim) | LLM 每支视频现写 manim 代码，重试 + VLM 修码兜底 | 定位最像、路线相反：我们"代码过闸入库、出片零现写、plan 是数据"正是其痛点的结构性解法；GitHub 无第二家做这套组合 |

五问对比：时间来源（音频事实+闸门 / TTS 时间戳 / 手写）、渲染单位（过闸组件 / 素材片段 / 现写代码）、LLM 角色（写 plan 数据）、质量关卡（**事前确定性闸门，独一份**）、配音（多 provider）。

## 二、对标片拆解：3b1b《Derivative formulas through geometry》（Chapter 3, Essence of calculus）

结构来源：[视频章节索引](https://github.com/tamnd/3blue1brown-index/blob/main/videos/2017/04/30/derivative-formulas-through-geometry-S0_qX4VJhMQ.md) + [幕后动画 demo](https://www.3blue1brown.com/lessons/manim-demo) + [官方场景源码仓 3b1b/videos](https://github.com/3b1b/videos)（eoc 目录）。

**结构**：七段式（Intro / x² / x³ / xⁿ / 1/x / Sine / Outro）——每段一个自足的几何动画单元；同一种视觉语法在每段重复：**一个主角图形 + 随解说的连续变换 + 贴图标签 + 颜色即语义**。

**镜头语言清单**（我们的货架能否承接）：

| 镜头语言 | 3b1b 做法 | 我们的状态 |
|---|---|---|
| 每秒都在动（updater 驱动） | 解说的每一秒画面都有对应运动，无静帧 | 部分达成：画布动点/描线连续（1.4.0）；插图有 Ken Burns；**列表/静段完全静止** |
| 图形持久 + 颜色即语义 | 旧对象淡出不消失，颜色跨场保持语义 | 达成：画布累积 + 每层一色 + 聚焦降暗（1.4.0） |
| 标签贴图形随动 | 标签钉在点/线旁，随图形移动 | **缺**：我们的文字（牌/字幕）与图形无空间关联 |
| 变换叙事（morph） | 形状 A 变换为 B（如三角形旋转 90° 从 sin 构造变 cos 构造） | **缺**：图层只"画出并保持"，无变换原语 |
| 辅助构造（ghost copies） | 相似三角形复制/旋转作辅助 | **缺** |
| 区域填充 | 面积叙事（x² 章的面积-斜率对偶） | **缺** |
| 公式一瞬且贴图形 | 公式 Write 后随图形联动 | 我们刻意不上公式（避开 TTS），符合定位 |
| 画布内镜头控制 | 摄像机推拉聚焦局部 | 低优先级候选 |

**知识区口播语法**（回形针/李永乐式）：每句解说一个图解锚点（平面动态图形 + 标签 + 箭头）、章节进度条、音效点。缺口：**箭头/标注层**、**音效点**（infra：音频 marker 扩 kind=sfx）。

**代码讲解语法**（Fireship 式）：代码面板逐行高亮 + 光标推进 + 打字机。缺口：`code_display` 的逐行高亮版（2.0）。

## 三、组件候选清单（按优先级，喂给后续货架生长）

1. **持续微动效默认态**——不是新组件，是组件演法的默认要求：任何静止超过一屏的画面都该有低幅持续运动（呼吸/漂移）。step_list 入场动效已有，静止期仍完全静止。
2. **`label_pin` 标签随动**——标签钉在图形锚点上随动（画布内部原语，math_canvas 扩展）。
3. **`ghost_transform` 变换原语**——形状 A→B 的幽灵变换（旋转三角形这类"构造升级"镜头）。
4. **`highlight_code` / code_display 2.0**——逐行高亮 + 光标推进 + 打字机。
5. **`arrow_note` 箭头标注层**——知识区图解标配。
6. **音效点**——infra 层音频 marker 扩 `kind=sfx`（现 marker_music 的姊妹）。
7. **`area_fill` 区域填充**——面积叙事（低优先级）。
8. **画布镜头**——演算画面内推拉聚焦（低优先级）。

## 四、借鉴清单（产品面，已部分执行）

- 烧录字幕（MPT 标配）✅ 已落地
- SKILL.md 驱动 agent 入口 ✅ 已有（与 MPT 撞车验证）
- MCP 工具化校验链（markdown_video 验证）→ P2 待做
- VLM 读片助手（TEA eval_suite 思路）→ P2 待做
- Kokoro 本地 TTS → P3 待做
- 不借鉴：素材库空镜匹配、生成式画面（与确定性定位冲突）
