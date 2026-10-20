# 公共 Plan 契约

以 [实际模型](../../../md2video/manifest/schema.py)、[迁移逻辑](../../../md2video/manifest/migration.py) 及 [渲染输入校验](../../../md2video/tools/render/manim_renderer_inputs.py) 为准。以下同时包含模型规则和风格工作流的自查要求；**Schema 通过不代表所有引用、画面和内容都已合格**。

## 内容、分镜与时间分开

- Plan 使用 `"version": "2"`，只有内容与目标意图，不手填 `start`、`end`、时长、帧数等执行时间。
- `segments` 是文字与朗读意图。风格制作使用 `title_main`、`title_sub`、`section_header`、`content`、`appendix`。
- `shots` 以有序 `segment_ids` 引用内容，代表连续的视觉执行单元。素材 marker 放在 Shot 的 `cues`，不要把 marker 当正文配音。
- `scenes` 决定素材策略、布局、渲染后端及可选表现组件，不在 Segment 上复制这些字段。
- 已有 v1 文件由加载器迁移；新文件不再生成旧字段。

## 朗读与文字载体

- 所有需要朗读的正文和小节标题都带 `audio_request`；例如 `{"voice": "zh-CN-YunxiNeural", "speed": 1.0}`。缺省格式是 `wav`。
- `title_main` / `title_sub` 只显示，不生成 TTS，放在独立的无组件标题场。
- **没有 `audio_request` 就是静默段**，不是自动配音。为画面有意安排静默可以，但必须有解释；不能把漏写当成已交付解说。
- `text` 同时是当前显示/组件输入文字与 TTS 文本，不承诺独立显示稿、朗读稿。
- Remotion 不在引擎正文层重复绘制被朗读的正文；这两个风格启用 `--subtitles`。组件显示了同文时字幕会按声明让位；这是单一文字载体，不是丢字幕。

## 引用与连续性自查

- Segment id 全局唯一，Shot id 全局唯一；每个 Segment 在计划中恰好引用一次，顺序与预期讲解一致。不要遗留孤儿或复制同一 Segment 来重播。
- 一次逐条展开的列表/代码/终端演示应在一个 Shot 内包含多段；这类组件按 Shot 重新挂载，不自动跨镜头累积。
- 数学画布按 Scene 挂载，可让同一 Scene id 在 `scenes` 中复现。其组件、后端和视觉参数必须一致，各 Shot id 仍然唯一。
- 统一显式写 `render_backend: "remotion"`，避免被全局默认 Manim 意外接管。组件引用必须有完整固定版本，不写“最新版”。
- `visual_type` 只表达素材策略，例如 `text_only`、`stock_image`、`gen_image`；不能写渲染后端名。各策略参数见 [组件与素材参考](components.md)。
- 现有布局模板有 `center_title_body`、`full_bleed_image_caption_bottom`、`image_top_text_bottom`。少用自定义区域；若确需 `layout_regions`，使用归一化坐标并通过约束，不手写引擎像素位置。

## 参考骨架

这是结构示意，不是默认风格。完整可执行示例分别位于 [技术讲解](../../md2video-tech-explainer/examples/cache.plan.json) 和 [数学可视化](../../md2video-math-explainer/examples/unit-circle.plan.json)。

```json
{
  "version": "2",
  "segments": [
    {"id": "title", "text": "主标题", "segment_type": "title_main"},
    {
      "id": "body", "text": "一句需要朗读的解释。", "segment_type": "content",
      "audio_request": {"voice": "zh-CN-YunxiNeural"}
    }
  ],
  "scenes": [
    {
      "id": "intro", "render_backend": "remotion",
      "shots": [{"id": "shot_intro", "segment_ids": ["title"]}]
    },
    {
      "id": "main", "render_backend": "remotion", "component": "step_list@1.0.2",
      "shots": [{"id": "shot_main", "segment_ids": ["body"]}]
    }
  ]
}
```

若需要单独检查 Schema，可在仓库根目录运行：

```text
uv run --locked --all-extras python -c "from pathlib import Path; from md2video.manifest.migration import load_plan_manifest_json; load_plan_manifest_json(Path(r'<绝对Plan路径>').read_text(encoding='utf-8')); print('schema OK')"
```

模型校验之外，上述顺序、完整性、旁白和画面合理性仍需自查。运行时还会经过布局、文字容量、素材、组件与时间线闸门；遇到拒绝不要绕过闸门。

## 可选的 BGM / 图片 marker

只使用已存在、获准使用的本地素材，路径相对于 Plan 所在目录。例如根级声明：

```json
{"media_declarations": {"music": {"calm": "assets/calm.wav"}}}
```

在一个 Shot 内添加 cue：

```json
{"cues": [{"id": "music_start_001", "cue_type": "marker_music", "kind": "start", "name": "calm", "position": "start"}]}
```

cue 必须有唯一 `id`，名称与声明一致。结束区间使用相同名称的 `kind: "end"` cue；没有结束 marker 的区间会延续至片尾。图片使用 `media_declarations.images` 与 `marker_image` 同理。非 Shot 起点的 cue 使用 `position: "before" / "after"` 和该 Shot 内的 `anchor_segment_id`，不直接填秒数。

不必强制加 BGM；缺文件时先报告或省略，不能让静默跳过素材变成未披露的降级交付。
