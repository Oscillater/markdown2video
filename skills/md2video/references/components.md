# 组件与素材参考

本目录只维护一份公共能力表。正式可用版本以 [已安装清单](../../../md2video/tools/render/remotion_backend/src/registered/installed.json) 为准，参数与行为可继续核对 [组件源码](../../../md2video/components/sources) 和 [素材工具](../../../md2video/tools/image)。不要从旧评测 Plan 推断“最新版”，也不要为了运行已有组件重复执行入库验收。

## 表现组件

Scene 上使用 `render_backend: "remotion"` 与 `component: "id@MAJOR.MINOR.PATCH"`。组件自带配色、字体、排版和动效，不消费设计包 token；它不能改变调度器的时间事实。

| 推荐引用 | 挂载 | 当前用途 | 文字与字幕 |
|---|---|---|---|
| `step_list@1.0.2` | Shot | 每个 `content` 一条，逐条出现并在本镜头保留 | 原文上屏，同文字幕让位；条目多/长会挤出画面，需拆分并抽帧 |
| `code_display@1.0.0` | Shot | 短代码/配置面板、行号和语法着色 | 原文上屏；不是代码执行器，也不是独立显示稿/解说稿通道 |
| `terminal@1.0.0` | Shot | 终端窗口，`$` 前缀表示命令，其余为输出样式 | 原文上屏；仅视觉演示，不会执行命令或验证输出 |
| `math_canvas@1.5.1` | Scene | 单位圆、动点、正弦/余弦的连续画布 | 不显示 Segment 原文，仍需要朗读字幕 |

旧版本仍可用于复现已有计划，新 Plan 优先选择表中版本。未知/未安装组件会警告并降级默认画面；不能因为没有报错就认为组件已生效。格式错误或把组件交给 Manim 则会提前失败。

标题卡放在独立无组件 Scene；小节标题可放进组件 Scene，由引擎在上层显示。正文组件排版不由引擎文字容量闸门兜底，必须抽帧确认。

### 数学画布参数

```json
{
  "component": "math_canvas@1.5.1",
  "visual_type": "text_only",
  "render_backend": "remotion",
  "visual_params": {
    "layers": [
      {"shot": "shot_sine", "kind": "sine"},
      {"shot": "shot_cosine", "kind": "cosine"}
    ]
  }
}
```

- 圆和动点是底座；不写 layers 时只显示底座，不能靠旁白自动产生曲线。
- `kind` 只有 `sine` / `cosine`；`shot` 是这个画布已有的起笔 Shot id。按发生顺序写层。
- 用同一 Scene id 复现各次访问，同一 id 的 `component`、后端和完整 `visual_params` 保持一致。
- 一个波层从自身锚点到下一波层锚点或画布末尾逐步描满；动点一章一圈。切走时活跃进度冻结，回来继续，历史曲线保留。
- 不支持任意函数、任意几何图形、自动公式排版或通用证明。扩展是另一个开发任务，需用户授权。

完整跨镜头示例见 [单位圆 Plan](../../md2video-math-explainer/examples/unit-circle.plan.json)。

## 素材策略

素材与组件是不同概念：`visual_type` 为每 Shot 准备素材，再按时间线叠加；`component` 是正文画面的实现。不要把渲染后端写成素材类型。

| 策略 | 参数 | 能力边界 |
|---|---|---|
| `text_only` | 无 | 不请求额外图片；可以搭配表现组件，不等于必须黑底字幕 |
| `stock_image` 本地 | `preferred_provider: "local"`，以及 `path` | 精确图片由用户/已有素材提供；路径相对 Plan。指定的本地文件无效会失败 |
| `stock_image` Pexels | `query`，可加 `preferred_provider: "pexels"` | 需要 `pexels` extra 与 `PEXELS_API_KEY`；搜索照片不保证概念图准确，需审核来源/适用性 |
| `gen_image` | 必填 `prompt`，可选 `style`、`palette`、`width`、`height` | Pillow 程序化抽象插画，prompt 作为稳定种子；不是理解提示词的 AI 生图 |

`gen_image` 支持：

- `style`：`orbit` / `layers` / `waves` / `blocks`。
- `palette`：`ink` / `moss` / `dusk`。
- 不渲染文字，不承诺精确流程、数据关系或数学图形。同一组参数确定性生成 PNG，便于缓存。

配图 Scene 的示意：

```json
{
  "visual_type": "gen_image",
  "visual_params": {"prompt": "层次与复用的抽象插画", "style": "layers", "palette": "ink"},
  "layout_type": "full_bleed_image_caption_bottom",
  "render_backend": "remotion"
}
```

`stock_video` 当前没有内置 provider。不要凭 LLM 提出了一个策略就声称管线能提供该素材。

## 风格与扩展边界

设计包负责引擎配色/字体/动效 token；风格 skill 负责叙事、演法、镜头和验收。单纯换肤优先使用设计包，组件自带视觉则不能靠设计包统一改色。

缺组件时：先说明内容与现有能力的差距，选择用户接受的现有素材，或在交付说明中记录缺口。只有获得扩展授权后才研究源码、注册与验收；不要在一次视频制作里擅自修改 `registered/` 文件。正式验收会真渲染、检查字幕声明、静态禁用 API、双跑一致性及黄金帧，并更新安装产物，不是普通制作的前置步骤。
