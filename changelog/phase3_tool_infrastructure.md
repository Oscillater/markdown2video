# Phase 3: 工具接口 + 基础设施

**日期**: 2026-04-11
**状态**: 已完成

## 概述

定义 Tool 统一抽象层（Protocol + Adapter + Registry + Cache），Pipeline 按 `visual_type` 动态调度工具。新增工具只需实现接口 + 注册，不改 Pipeline 核心代码。同步修复 LLM Prompt 已知问题，建立时长对齐契约（`target_duration`）。

**单元测试**: 229 passed（原 187 + 新增 42）

## 修改文件

### 新建（11 文件）

| 文件 | 说明 |
|------|------|
| `md2video/tools/protocol.py` | Tool Protocol（`tool_type`, `provider_name`, `execute()`） |
| `md2video/tools/adapter.py` | Adapter Protocol + ExecutionMode 常量 |
| `md2video/tools/adapter_impl.py` | InProcessAdapter / CliAdapter / HttpAdapter 实现 |
| `md2video/tools/cache.py` | ToolCache 统一缓存层（sha256 key，按 tool_type 分目录） |
| `md2video/tools/registry.py` | ToolRegistry（visual_type + provider → Tool 实例） |
| `md2video/tools/render/manim_tool.py` | ManimRenderTool（Protocol stub，渲染逻辑暂留 Pipeline） |
| `tests/test_tool_protocol.py` | Protocol 测试（10 tests） |
| `tests/test_tool_cache.py` | 缓存测试（10 tests） |
| `tests/test_tool_registry.py` | Registry 测试（6 tests） |
| `tests/test_dispatch.py` | Dispatch + priority 测试（7 tests） |
| `tests/test_manim_tool.py` | ManimRenderTool 测试（4 tests） |

### 修改（12 文件）

| 文件 | 改动 |
|------|------|
| `md2video/core/planner/llm_planner.py` | prompt: visual_type 加 manim, fallback → preferred_provider |
| `md2video/tools/tts/edge_tts.py` | 添加 Protocol 属性 + execute()，迁移到 ToolCache |
| `md2video/config.py` | 新增 ToolConfig, DEFAULT_TOOL_PRIORITY |
| `md2video/core/pipeline.py` | Registry + dispatch + priority + _render_manim_batch 提取 + _fill_target_durations |
| `md2video/manifest/schema.py` | ShotPlan.target_duration 字段 |
| `md2video/tools/__init__.py` | 导出 Tool |
| `md2video/tools/tts/__init__.py` | 导出 EdgeTTSTool |
| `md2video/tools/render/__init__.py` | 导出 ManimRenderTool |
| `tests/test_edge_tts.py` | 缓存 key 格式更新 + Protocol 测试 |
| `tests/test_llm_planner.py` | fallback → preferred_provider |
| `tests/test_schema.py` | target_duration 测试 + 向后兼容 |
| `TODO.md` | Phase 3 标记完成 |

---

## 详细改动

### 1. Tool Protocol

**文件**: `md2video/tools/protocol.py`

```python
@runtime_checkable
class Tool(Protocol):
    @property
    def tool_type(self) -> str: ...      # "tts" | "image" | "video" | "render"
    @property
    def provider_name(self) -> str: ...  # "edge-tts" | "manim" | "pexels" | ...
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]: ...
```

遵循现有 Planner Protocol 模式（`@runtime_checkable`），只定义 JSON 输入输出契约，不绑定执行方式。

### 2. Adapter Protocol

**文件**: `md2video/tools/adapter.py`, `md2video/tools/adapter_impl.py`

三种适配器实现：

| 适配器 | 执行方式 | 适用场景 |
|--------|---------|---------|
| InProcessAdapter | 直接调用 `tool.execute()` | Python 工具（EdgeTTSTool） |
| CliAdapter | 子进程 + stdin/stdout JSON | CLI 工具（ffmpeg 等） |
| HttpAdapter | HTTP POST + JSON | 外部 API（Pexels、Remotion 等） |

### 3. 统一缓存层

**文件**: `md2video/tools/cache.py`

```python
class ToolCache:
    make_key(tool_type, params) → str    # sha256("{tool_type}:{json(params)}")
    has(tool_type, cache_key) → bool
    read/write/read_json/write_json(...)
```

目录结构: `{cache_root}/{tool_type}/{hash}.{ext}`

EdgeTTSTool 从 md5 自定义缓存迁移到 ToolCache（sha256 key），旧缓存自动失效。

### 4. EdgeTTSTool 适配

**文件**: `md2video/tools/tts/edge_tts.py`

- 添加 `tool_type="tts"`, `provider_name="edge-tts"`, `execute()` 属性/方法
- `execute()` 内部调用已有 `synthesize()`，不改功能
- 缓存迁移到 ToolCache

### 5. ManimRenderTool

**文件**: `md2video/tools/render/manim_tool.py`

Protocol stub。渲染逻辑仍由 Pipeline 的 `_render_manim_batch()` 处理（子进程 + 文件系统），Phase 5 迁移到 `execute()` 中。

### 6. ToolRegistry

**文件**: `md2video/tools/registry.py`

```python
class ToolRegistry:
    register(visual_type, tool)       # 注册工具
    get_tool(visual_type, provider)   # 获取工具
    has(visual_type, provider)        # 检查是否存在
    get_providers(visual_type)        # 列出已注册 provider
```

### 7. Pipeline 重构

**文件**: `md2video/core/pipeline.py`

核心变化：

1. `__init__`: 创建 ToolRegistry，注册 EdgeTTSTool 和 ManimRenderTool
2. TTS 步骤: `tts_tool.execute({...})` 替代直接 `synthesize()` 调用
3. 新增 `_dispatch_tool()`: 按 visual_type 查优先级序列，按序尝试 provider
4. `preferred_provider` 支持: LLM 建议的 provider 优先尝试
5. `_text_only` 降级: 全部失败时降级为 text_only Manim 渲染
6. `_render_manim_batch()`: 从 inline 代码提取为独立方法
7. `_fill_target_durations()`: TTS 后填充 ShotPlan.target_duration

### 8. ToolConfig

**文件**: `md2video/config.py`

```python
DEFAULT_TOOL_PRIORITY = {
    "text_only": ["manim"],
    "tts": ["edge-tts"],
    "stock_image": ["pexels", "pixabay", "_text_only"],
    "stock_video": ["pexels_video", "pixabay_video", "_text_only"],
}
```

### 9. 时长对齐契约

**文件**: `md2video/manifest/schema.py`

`ShotPlan` 新增 `target_duration: float = 0.0`，由 Pipeline 在 TTS 后从 segment 时长计算填充，写入 plan.json。Phase 4 的视觉工具据此适配输出时长。

### 10. LLM Prompt 修复

**文件**: `md2video/core/planner/llm_planner.py`

- `BLUEPRINT_SYSTEM_PROMPT`: `visual_type` 列表加入 `manim`
- `visual_params.fallback` → `visual_params.preferred_provider`
- `SYSTEM_PROMPT`（legacy）同步更新

---

## 测试

**总计 229 tests（新增 42）**

| 文件 | Tests | 覆盖内容 |
|------|-------|---------|
| `test_tool_protocol.py` | 10 | Protocol isinstance 检查、Adapter 模式、InProcessAdapter.invoke |
| `test_tool_cache.py` | 10 | key 确定性/敏感性、read/write round-trip、JSON round-trip |
| `test_tool_registry.py` | 6 | register/get/has/providers/overwrite |
| `test_dispatch.py` | 7 | 优先级排序、preferred_provider、_text_only 降级、全部失败 |
| `test_manim_tool.py` | 4 | Protocol conformance、NotImplementedError |
| `test_edge_tts.py` | +3 | tool_type/provider_name/execute 测试 |
| `test_schema.py` | +2 | target_duration 默认值、JSON round-trip、向后兼容 |
| `test_llm_planner.py` | 更新 | fallback → preferred_provider |
