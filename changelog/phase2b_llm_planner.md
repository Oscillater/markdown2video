# Phase 2B: LLM Planner 两阶段全局导演方案

**日期**: 2026-04-04
**状态**: 已完成

## 概述

实现两阶段 LLM Planner，取代初版单阶段调用。核心思路：Scene 是视觉模板（Style Class），Shot 是镜头实例（Instance）。LLM 不再"数句子"，而是负责"定义风格"和"语义分镜"。

## 三阶段流程

### 第一阶段：全局定调 `_global_blueprint()`

- 输入：完整 Markdown 原文
- LLM 任务：定义 3~5 个 Scene 模板（Scene Registry）
- 产出：`List[SceneTemplate]`（id, name, description, visual_type, visual_params）
- 意义：确立视觉天花板，无论文本多长，视觉只在这几种风格中切换

### 第二阶段：局部分镜 `_chunk_mapping()`

- 输入：Scene Registry + 当前章节的 Segment 列表（Chunk）
- LLM 任务：Shot 划分（切分连续镜头）+ Scene 映射（从菜单选 Scene ID）
- 产出：`List[ShotMapping]`（scene_id + segment_ids）
- 意义：分块处理，不受长度限制；通过 ID 引用保证跨章节风格一致

### 第三阶段：框架重组 `_reconcile()`

- 合并所有 chunk 的映射
- 按 scene_id 分组：相同模板的 Shot 合并到同一个 ScenePlan
- 校验：去重、连续性、完整性、文本完整性
- 拆分 explicit segment 为 singleton scene
- ID 补全：scene/shot 全局递增编号

## 修改文件

- `md2video/core/planner/llm_planner.py` — 核心重构
- `md2video/core/planner/__init__.py` — 懒导出新类型
- `md2video/config.py` — 新增 MAX_CHUNK_SEGS
- `md2video/cli.py` — 新增 --planner 参数
- `md2video/core/pipeline.py` — Planner 创建逻辑
- `tests/test_llm_planner.py` — 25 tests
- `.env.example` — LLM 配置示例
- `TODO.md` / `README.md` / `CLAUDE.md` — 文档更新

---

## 数据结构

**文件**: `md2video/core/planner/llm_planner.py`

### 新增模型

```python
class SceneTemplate(BaseModel):
    """第一阶段产出的 Scene 模板。"""
    id: str                          # e.g. "SCENE_CONCEPT"
    name: str                        # e.g. "概念讲解"
    description: str                 # LLM 对该风格的描述
    visual_type: str                 # text_only / stock_image / stock_video
    visual_params: Dict              # 公共参数（query, fallback 等）

class ShotMapping(BaseModel):
    """第二阶段产出的 shot-scene 映射。"""
    scene_id: str                    # 引用 SceneTemplate.id
    segment_ids: List[str]

class BlueprintOutput(BaseModel):
    """第一阶段输出。"""
    scene_templates: List[SceneTemplate]

class ChunkMappingOutput(BaseModel):
    """第二阶段输出。"""
    shots: List[ShotMapping]
```

### 保留的旧版模型

`LlmShot`, `LlmScene`, `LlmPlannerOutput` 保留用于 `_convert()` 兼容方法。

---

## LlmPlanner 类重构

### 旧版

```python
class LlmPlanner:
    def __init__(self, ...):
        self._agent = Agent(...)       # 单个 agent
        @agent.tool_plain
        def submit_plan(...): ...

    def plan(self, segments):
        return self._convert(segments, llm_output)
```

### 新版

```python
class LlmPlanner:
    def __init__(self, ...):
        self._blueprint_agent = Agent(...)   # 第一阶段 agent
        self._mapping_agent = Agent(...)      # 第二阶段 agent
        @blueprint_agent.tool_plain
        def submit_blueprint(...): ...
        @mapping_agent.tool_plain
        def submit_chunk_mapping(...): ...

    def plan(self, segments):
        return self._plan_two_pass(segments)

    def _plan_two_pass(self, segments):
        registry = self._global_blueprint(segments)
        chunks = self._split_chunks(segments)
        all_mappings = [self._chunk_mapping(c, registry) for c in chunks]
        return self._reconcile(all_mappings, segments, registry)
```

---

## 分块策略 `_split_chunks()`

**文件**: `md2video/core/planner/llm_planner.py`

纯静态方法，按 section_context 切分 segments：

| 规则 | 描述 |
|------|------|
| title 归入首块 | `title_main` / `title_sub` 始终归入第一个 content chunk |
| section 切分 | `section_context` 变化时切分新 chunk |
| 长度切分 | 单 chunk 超过 `MAX_CHUNK_SEGS`（30）时强制切分 |

---

## 合并逻辑 `_reconcile()`

**文件**: `md2video/core/planner/llm_planner.py`

核心变化：相同 scene_id 的 ShotMapping 合并到同一个 ScenePlan。

```python
# 旧版：每个 mapping → 一个 scene（11 scenes）
for mapping in flat_mappings:
    scenes.append(ScenePlan(...))

# 新版：按 scene_id 分组 → 一个 scene 含多个 shots（~5 scenes）
scene_groups = defaultdict(list)
for mapping in flat_mappings:
    scene_groups[mapping.scene_id].append(non_exp_ids)
for scene_id, shot_groups in scene_groups.items():
    scenes.append(ScenePlan(shots=[ShotPlan(...) for ...]))
```

### 校验

| 校验 | 描述 |
|------|------|
| scene_id 存在性 | 每个 mapping 的 scene_id 必须在 registry 中 |
| segment 唯一性 | 每个 segment 恰好出现一次 |
| segment 连续性 | 每个 shot 内 segment 全局连续 |
| 文本完整性 | 所有 segment 都被覆盖（`_validate_text_integrity`） |
| explicit 保护 | explicit segment 拆为 singleton scene |

---

## 配置

**文件**: `md2video/config.py`, `.env.example`

```python
MAX_CHUNK_SEGS = 30    # 单 chunk 最大 segment 数

@dataclass
class PlannerConfig:
    default: str = "rule"          # "rule" or "llm"
    model: str = "openai:gpt-4o"
    api_key: str = ""
    base_url: str = ""             # 兼容中转站
```

```env
MD2VIDEO_PLANNER=llm
OPENAI_API_KEY=sk-...
MD2VIDEO_LLM_MODEL=openai:gpt-4o
MD2VIDEO_LLM_BASE_URL=https://your-api-endpoint/v1
```

---

## 测试

**文件**: `tests/test_llm_planner.py`（25 tests）

### TestConvert（7 tests）— 旧版兼容

| 测试 | 覆盖 |
|------|------|
| `test_convert_basic` | 基本 scene/shot 转换 |
| `test_convert_multi_shot_per_scene` | 一个 scene 含多个 shot |
| `test_convert_explicit_preserved` | explicit 拆为 singleton |
| `test_convert_duplicate_segment_raises` | 重复 segment 报错 |
| `test_convert_missing_segment_raises` | 缺少 segment 报错 |
| `test_convert_non_consecutive_raises` | 非连续 segment 报错 |
| `test_convert_unknown_segment_raises` | 未知 segment 报错 |

### TestPlanFallback（4 tests）

| 测试 | 覆盖 |
|------|------|
| `test_empty_input` | 空输入 |
| `test_fallback_on_convert_error` | 校验失败 fallback |
| `test_scene_and_shot_ids_sequential` | ID 递增（新版：合并后） |
| `test_all_segments_covered` | 全覆盖 |

### TestSplitChunks（5 tests）— 新增

| 测试 | 覆盖 |
|------|------|
| `test_single_chunk` | 不足 max_segs |
| `test_split_by_section` | section_context 切分 |
| `test_split_by_max_segs` | 长度强制切分 |
| `test_empty_input` | 空输入 |
| `test_single_segment` | 单 segment |

### TestReconcile（7 tests）— 新增

| 测试 | 覆盖 |
|------|------|
| `test_basic_reconcile` | 基本合并 |
| `test_reconcile_sequential_ids` | 合并后 ID 递增 |
| `test_reconcile_explicit_preserved` | explicit 拆分 |
| `test_reconcile_unknown_scene_raises` | 未知 scene_id |
| `test_reconcile_missing_raises` | 缺少 segment |
| `test_reconcile_non_consecutive_raises` | 非连续 segment |
| `test_reconcile_same_scene_merged` | 相同 scene_id 合并 |

### TestTextIntegrity（2 tests）— 新增

| 测试 | 覆盖 |
|------|------|
| `test_integrity_ok` | 全覆盖通过 |
| `test_integrity_missing_raises` | 遗漏报错 |

---

## 已知问题

- LLM 分镜 prompt 仍需调优（可能出现非连续段落归入同一 scene）
- Scene Registry 模板信息未写入 plan.json（scene 只存 visual_type/visual_params 副本）
