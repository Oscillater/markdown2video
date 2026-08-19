# Phase 4: 现有工具重构

**日期**: 2026-04-14
**状态**: 已完成

## 概述

修正代码与架构规范的偏差，打通 Phase 5 路径。Pipeline 实现按 scene 粒度的工具分发（per-scene dispatch），Assembler 消费 per-shot 视觉产物（`extract_shot_visual_entries`），清理死代码（Adapter 层、LLM Planner 旧版 `_convert` 路径及对应测试）。

**单元测试**: 222 passed（原 229，删除 7 个已废弃的适配器/旧版测试）

## 修改文件

### 删除（4 文件）

| 文件 | 说明 |
|------|------|
| `md2video/tools/adapter.py` | Adapter Protocol + ExecutionMode 常量（未使用，删除） |
| `md2video/tools/adapter_impl.py` | InProcessAdapter / CliAdapter / HttpAdapter（未使用，删除） |

### 修改（9 文件）

| 文件 | 改动 |
|------|------|
| `md2video/core/pipeline.py` | per-scene dispatch + `_invoke_visual_tool()` + `_apply_visual_result()` |
| `md2video/assembler/ffmpeg_assembler.py` | `extract_shot_visual_entries()` 消费 per-shot visuals |
| `md2video/tools/protocol.py` | `execute()` 文档补充 Visual/TTS 工具输入输出契约 |
| `md2video/core/planner/llm_planner.py` | 删除旧版 `_convert()`、`LlmPlannerOutput`、`LlmScene`、`LlmShot` |
| `tests/test_dispatch.py` | 重写：per-scene dispatch 测试 + `_invoke_visual_tool` + `_apply_visual_result`（220 行） |
| `tests/test_llm_planner.py` | 删除旧版 `_convert` 相关测试（186→14 行） |
| `tests/test_tool_protocol.py` | 删除 Adapter 测试（56→3 行） |
| `tests/test_ffmpeg_extractor.py` | 新增 per-shot visual entry 提取测试（+68 行） |
| `TODO.md` | Phase 4 标记完成 |

---

## 详细改动

### 1. Pipeline per-scene 工具调度

**文件**: `md2video/core/pipeline.py`

#### `_dispatch_render()` 重构

从"全部走 Manim 批量渲染"改为按 scene 粒度分发：

```python
def _dispatch_render(self, plan, result, md_path):
    for sc in plan.scenes:
        if sc.shots and sc.visual_type != "text_only":
            self._dispatch_visual_tool(sc, plan, result)
    return self._render_manim_batch(md_path)
```

- non-`text_only` scene 走 `_dispatch_visual_tool()`（按优先级尝试 provider）
- `text_only` scene 统一走 `_render_manim_batch()`（Manim CLI 子进程）
- Result Manifest 保存延迟到 dispatch 之后（确保 visual 已填充）

#### `_dispatch_visual_tool()` 新增

为单个 scene 按优先级尝试 provider，首个成功即填充 `ShotResult.visual`：

```python
def _dispatch_visual_tool(self, scene_plan, plan, result):
    visual_type = scene_plan.visual_type
    preferred = scene_plan.visual_params.get("preferred_provider")
    providers = self.tool_config.get_priority(visual_type)
    # 按 preferred → priority 序列尝试，全部失败仅 WARNING，不中断流程
```

#### `_invoke_visual_tool()` 新增

通用工具调用，构建标准化 input_data 并写回结果：

```python
input_data = {
    "scene": {"id", "visual_type", "visual_params", "section_context"},
    "shot":  {"id", "segment_ids", "target_duration"},
    "segments": [{"id", "text", "segment_type", "audio"}],
    "output_dir": str,
}
output = tool.execute(input_data)
self._apply_visual_result(output, shot_plan.id, result)
```

#### `_apply_visual_result()` 新增

将 `tool.execute()` 输出的 `visuals[]` 写回 `result.scenes` 中匹配的 `ShotResult.visual`：

```python
for vis in visuals:
    if vis.get("shot_id") == shot_plan_id:
        shot_result.visual = VisualResult(path=..., width=..., height=..., source=...)
```

### 2. Assembler 消费 per-Shot 视觉产物

**文件**: `md2video/assembler/ffmpeg_assembler.py`

#### `extract_shot_visual_entries()` 新增

遍历 `result.scenes[].shots[].visual`，收集非空 visual 的 shot，生成 ffmpeg overlay 条目：

```python
def extract_shot_visual_entries(self, result: ResultManifest):
    entries = []
    for sc in result.scenes:
        for shot in sc.shots:
            vis = shot.visual
            if vis and vis.path and vis.source != "none":
                entries.append({
                    "path": vis.path,
                    "start": shot.start,
                    "end": shot.end,
                    "source": vis.source,
                })
    return entries
```

在 `assemble()` 中与 marker-based image entries 合并，统一进入 ffmpeg filter graph。

### 3. Tool Protocol 契约文档

**文件**: `md2video/tools/protocol.py`

`execute()` 方法补充 Visual tool 和 TTS tool 的输入输出契约（docstring），明确 JSON 结构，供未来工具实现参考。

### 4. 死代码清理

**文件**: `md2video/core/planner/llm_planner.py`

删除旧版代码：
- `_convert()` 方法（旧版单阶段 LLM 输出 → ScenePlan 转换）
- `LlmPlannerOutput`、`LlmScene`、`LlmShot` 数据结构
- `SYSTEM_PROMPT`（旧版 legacy prompt）

**文件**: `md2video/tools/adapter.py`, `md2video/tools/adapter_impl.py`

完全删除。Adapter Protocol（InProcess / CLI / HTTP）在 Phase 3 定义但从未被 Pipeline 或任何工具使用。当 Phase 5/6 需要外部工具时，按需重新实现。

### 5. 测试变更

**总计 222 tests（原 229，净减 7）**

| 文件 | 变化 | 说明 |
|------|------|------|
| `test_dispatch.py` | 7→20 (+13) | per-scene dispatch、`_invoke_visual_tool`、`_apply_visual_result`、preferred_provider、全部失败降级 |
| `test_llm_planner.py` | 25→14 (-11) | 删除 `_convert` 相关 11 个测试 |
| `test_tool_protocol.py` | 10→4 (-6) | 删除 Adapter Protocol + InProcess/Cli/Http Adapter 测试 |
| `test_ffmpeg_extractor.py` | +4 | `extract_shot_visual_entries` 提取、空 visual 跳过、source=none 跳过、多 scene 合并 |

---

## 架构影响

Phase 4 完成后，Pipeline 已具备完整的工具调度能力：

```
Scene (non-text_only) → _dispatch_visual_tool()
    → preferred_provider 优先尝试
    → DEFAULT_TOOL_PRIORITY 序列兜底
    → _invoke_visual_tool() 构建 input_data
    → tool.execute(input_data) → output
    → _apply_visual_result() 写回 ShotResult.visual
    → Result Manifest 保存

Scene (text_only) → _render_manim_batch()（Manim CLI 子进程，行为不变）

Assembler → extract_shot_visual_entries() → ffmpeg overlay
```

新增 Image Tool（Phase 5）只需：实现 Tool Protocol + 注册到 Registry + Pipeline 自动调度。
