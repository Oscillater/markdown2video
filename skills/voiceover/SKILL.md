# 口播 skill：技术知识口播

把一篇技术向知识 markdown 变成一份 `plan.json`，跑出一条**至少能看、不划走**的竖屏片。

## 角色分工

- **代码负责流程**：配音（edge-tts）、渲染（manim / Remotion）、装配（FFmpeg）、时间闸门，全部由管线执行，你不写代码、不算时间。
- **你负责内容**：讲什么、按什么顺序、哪里用哪种演法、画面连续性怎么切。所有内容决定都落在 `plan.json` 里。
- plan 落盘后执行侧零自由裁量：同一份 plan 永远渲染出同一条片。

## 工作流（五步）

1. **读稿定结构**：通读 markdown，划出钩子、小节、收尾；判断哪些内容适合哪种演法。
2. **写 plan.json**：按下面的「结构套路」「切镜规则」「组件货架」产出 plan。
3. **跑管线**：`python -m md2video --plan <plan.json> -o <out.mp4>`。产物在 `artifacts/runs/<run_id>/`。
4. **读片迭代**：查 warnings、查 viewer、抽帧看关键画面，改 plan 重跑，直到过关。
5. **交付**：成片路径 + run 目录 + 遗留问题清单。

## 结构套路

- **开场**：`title_main` + `title_sub`（一张标题卡）→ 一句 `content` 钩子。钩子要在 3 秒内给出"为什么值得看完"。
- **小节**：每节一个 `section_header`，一节 1~3 个镜头；一节只讲一件事。
- **收尾**：一两句收束，回扣钩子。
- **节奏**：一句话一个 `content` segment，单句 ≤ 40 字（口播约 8~12 秒）；全片 1.5~3 分钟为宜。
- 小节之间靠 `section_header` 换气，不要让一节超过 4 个镜头。

## 切镜规则

- **Shot = 一次连续拍摄**。画面需要连续演进的内容（推理链、演示过程、逐步展开的图示）必须放进**同一个 shot**（一个 shot 可以带多个 segment_ids）。
- 话题转折、演法更换 → 新 shot / 新 scene。
- 不确定切不切时：内容能各自独立成立就切，需要前文铺垫才看懂就不切。

## 组件货架

场景级引用：`"render_backend": "remotion"` + `"component": "<id>@<version>"`。组件逐 shot 接管正文画面；**标题卡与 section 堆叠字幕归引擎——不要把 title/section_header 段放进组件场景**。

| id | 适合的内容 | 显示规则 |
|---|---|---|
| `step_list@1.0.0` | 步骤、并列要点（每个 segment 一条，逐条浮现） | 圆形序号 + 文字 |
| `code_display@1.0.0` | 配置、数据结构、短代码（GitHub 深色面板） | 行号 + 语法着色 |
| `terminal@1.0.0` | 命令演示（黑窗口） | `$` 前缀 = 命令行，其余 = 灰色输出 |

**硬约束：组件显示的文本就是朗读文本**（TTS 读的就是 segment 的 text）。所以：

- 命令保持短（≤ 20 字符），选"读出来不别扭"的命令；
- 代码示例选"读出来也像人话"的内容；
- "显示文本 ≠ 朗读文本"的诉求先记进交付说明，不要硬凑。

## plan 怎么写

骨架：

```json
{
  "version": "2",
  "segments": [
    {"id": "title_main_001", "text": "标题", "segment_type": "title_main"},
    {"id": "content_001", "text": "一句话。", "segment_type": "content",
     "section_context": "小节名", "audio_request": {"voice": "zh-CN-YunxiNeural"}}
  ],
  "scenes": [
    {"id": "scene_001", "visual_type": "text_only", "render_backend": "remotion",
     "section_context": "开场",
     "shots": [{"id": "shot_001", "segment_ids": ["title_main_001"]}]},
    {"id": "scene_002", "visual_type": "text_only", "render_backend": "remotion",
     "component": "step_list@1.0.0",
     "shots": [{"id": "shot_002", "segment_ids": ["content_001"]}]}
  ]
}
```

校验清单（管线会 fail fast，先自查）：

- [ ] **所有要朗读的 segment 都必须带 `audio_request`（含 section_header）**——没有它就是静默段，管线不会读也不会警告。title_main / title_sub 例外：标题卡只显示、永不朗读。
- [ ] `segment_type` 只用：title_main / title_sub / section_header / content / appendix。
- [ ] 每个 content 类 segment 恰好出现在一个 shot 里；无孤儿、无重复。
- [ ] plan 不含任何时间字段（时长由配音事实决定）。
- [ ] 组件场景必须 `render_backend: "remotion"`；ref 带版本（`@1.0.0`）。
- [ ] shot 内 segment_ids 顺序 = 朗读顺序。
- [ ] 全片统一一个 backend（本 skill 用 remotion），不要混 manim。

## 跑管线

```text
python -m md2video --plan <plan.json> -o <out.mp4>
```

- 配音默认 edge-tts（zh-CN-YunxiNeural），需要网络；可在 segment 上用 `audio_request` 调 voice/speed。
- 全部产物在 `artifacts/runs/<run_id>/`：`result.json`（warnings + artifact index）、`manifest_viewer.html`（人读的检查页）、`timeline.json`（时间事实）、`plan.json`、`execution-assets.json`。

## 读片迭代

按顺序检查，改完重跑：

1. **result.json 的 warnings**：逐条处理。常见：
   - `not registered` / `not installed` → 组件 ref 写错或未入库，改 ref；
   - 时长差异告警 → segment 文本过长，拆句；
   - 降级 warning → 用了引擎不认识的能力名，换名字。
   - **TTS: 0 audio assets / 成片远短于预期 → plan 里漏了 `audio_request`**，全片按静默段渲染，且不会有任何警告。
2. **viewer**：shot 数量、每段时长、cue 落位是否合预期。
3. **抽帧**：对组件 shot 抽 1~2 帧，确认画面挂上了（终端黑窗 / 步骤列表 / 代码面板），正文没掉回默认渲染：
   `ffmpeg -y -ss <秒> -i <成片> -frames:v 1 frame.png`
4. **听感**（需要人）：命令句、代码句让用户听一遍，别扭的改写文本。

## 缺组件怎么办

货架上没有合适的演法时，走组件提案流程（契约见 `docs/architecture.md` A8 节）：

1. 写组件源码 `<id>.tsx` + 注册模块 `register.py`，放 `md2video/components/sources/<id>/`；
2. 验收入库：`python -m md2video.check_component md2video.components.sources.<id>.register`（禁网扫描 → 双跑逐帧一致 → 黄金帧存档，失败自动回滚）；
3. 入库后按 `id@version` 引用。

底线：组件不改时间事实、禁 random/网络/fs、双跑逐帧一致。
