# Phase 2: Shot 层引入 + 三层数据模型

**日期**: 2026-04-02
**状态**: 已完成（未提交）

## 概述

在 Phase 2A（Segment → Scene 双层模型）基础上，引入 **Shot（镜头）** 作为中间层，升级为 **Segment → Shot → Scene** 三层数据模型。

- **Segment**：最小时间单元（一句话），TTS 单位
- **Shot**：时间连续的最小视觉单元，由连续 Segment 组成，每个 Shot 调用一个工具
- **Scene**：语义级别的风格分组，由多个 Shot 聚合而成，共享同一套视觉方案

当前 RulePlanner 每个 Scene 1:1 映射一个 Shot（行为不变，结构升级），为后续 LLM Planner 做多 Shot 划分 + Scene 聚合做准备。

## 核心设计

**为什么需要三层：**
- Shot 保证时间连续性：每个 Shot 对应一段连续画面，工具按 Shot 粒度生成视频/图片
- Scene 保证风格一致性：多个讲"神经网络"的镜头可能散落在不同时间点，但共享同一套视觉风格
- Planner 在 Scene 层做语义决策，Tool 在 Shot 层执行生成

**向后兼容：**
- 旧 JSON 含 `scene.segment_ids` 时，`model_validator` 自动迁移为单 Shot
- 旧 JSON 含 `scene_result.segment_ids` / `scene_result.visual` 时同理自动迁移
- 迁移字段标记 `exclude=True`，序列化时不输出旧字段

## 修改文件

- `md2video/manifest/schema.py`
- `md2video/core/planner/rule_planner.py`
- `md2video/core/pipeline.py`
- `md2video/tools/render/manim_renderer.py`
- `tests/test_schema.py`
- `tests/test_rule_planner.py`
- `TODO.md`

---

## Schema: 新增 ShotPlan / ShotResult

**文件**: `md2video/manifest/schema.py`

### 新增模型

```python
class ShotPlan(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)

class ShotResult(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    visual: VisualResult = Field(default_factory=VisualResult)
```

### ScenePlan 变化

```python
# 旧 (Phase 2A)
class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = ...
    segment_ids: List[str] = ...   # 直接包含 segment
    section_context: str = ""

# 新 (Phase 2)
class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = ...
    shots: List[ShotPlan] = ...    # 通过 Shot 间接包含 segment
    section_context: str = ""
    segment_ids: Optional[List[str]] = Field(default=None, exclude=True)  # 向后兼容

    @property
    def all_segment_ids(self) -> List[str]:  # 便捷属性，展开所有 shot 的 segment_ids
        return [sid for shot in self.shots for sid in shot.segment_ids]

    @model_validator(mode="after")
    def _migrate_segment_ids(self):  # 旧 JSON segment_ids → 单 Shot
        ...
```

### SceneResult 变化

```python
# 旧 (Phase 2A)
class SceneResult(BaseModel):
    id: str
    segment_ids: List[str] = ...
    start: float = 0.0
    end: float = 0.0
    visual: VisualResult = ...

# 新 (Phase 2)
class SceneResult(BaseModel):
    id: str
    shots: List[ShotResult] = ...
    start: float = 0.0
    end: float = 0.0
    segment_ids: Optional[List[str]] = Field(default=None, exclude=True)  # 向后兼容
    visual: Optional[VisualResult] = Field(default=None, exclude=True)

    @property
    def all_segment_ids(self) -> List[str]: ...

    @model_validator(mode="after")
    def _migrate_and_sync(self):
        # 1. 旧 JSON segment_ids → 单 Shot
        # 2. 从 shots 聚合 start/end
        ...
```

---

## Rule Planner: 适配 Shot 结构

**文件**: `md2video/core/planner/rule_planner.py`

### 变化

每个 Scene 当前拆为恰好一个 Shot（1:1 映射），分组规则不变：

```python
# 旧 (Phase 2A)
ScenePlan(id=f"scene_{counter:03d}", segment_ids=[s.id for s in buf], ...)

# 新 (Phase 2)
ScenePlan(id=f"scene_{counter:03d}", shots=[ShotPlan(id=f"shot_{shot_counter:03d}", segment_ids=[s.id for s in buf])], ...)
```

Shot ID 全局递增（`shot_001`, `shot_002`, ...），跨 Scene 连续。

### denormalize 变化

```python
# 旧: 遍历 scene.segment_ids
for seg_id in scene.segment_ids:
    scene_map[seg_id] = scene

# 新: 遍历 scene.shots → shot.segment_ids
for shot in scene.shots:
    for seg_id in shot.segment_ids:
        scene_map[seg_id] = scene
```

---

## Pipeline: 构建 ShotResult

**文件**: `md2video/core/pipeline.py`

`_build_scene_results()` 变化：先为每个 Shot 构建 ShotResult，再聚合为 SceneResult。

```python
# 旧: 直接从 segment 算 scene 的 start/end
starts = [result_map[sid].start for sid in sp.segment_ids ...]
scene_results.append(SceneResult(id=sp.id, segment_ids=sp.segment_ids, start=min(...), end=max(...)))

# 新: 先构建 shot_results，再聚合
shot_results = []
for shot_plan in sp.shots:
    shot_results.append(ShotResult(id=shot_plan.id, segment_ids=..., start=..., end=...))
scene_results.append(SceneResult(id=sp.id, shots=shot_results, ...))
```

---

## Manim Renderer: 使用 all_segment_ids

**文件**: `md2video/tools/render/manim_renderer.py`

所有 `scene.segment_ids` 替换为 `scene.all_segment_ids`（3 处）：

- `construct()` 中构建 segment→scene 映射
- `_construct_by_scenes()` 中分离 title scenes / other scenes
- `_construct_by_scenes()` 中遍历 scene 内的 segment

---

## TODO.md 更新

- 架构图：双层数据模型 → 三层数据模型 (Segments / Shots / Scenes)
- Section 3.2.1: 拆分为 Shot（镜头）和 Scene（风格组）两个子节，含定义、关系、动机、示例
- Section 3.3: Manifest 示例改为含 `shots` 结构，三层关联关系说明
- Section 3.4: Planner 职责从两项扩展为三项（Shot 划分 + Scene 聚合 + 视觉决策）
- Section 3.5/3.7: 工具输入改为 Shot 粒度，时长对齐从 Scene 改为 Shot
- Section 7: 代码映射表更新状态列，标注需适配 Shot 的模块
- Section 8: 路线图重组为 Phase 2（Shot + LLM）、Phase 3（Tool 接口）、Phase 4（具体工具）、Phase 5（模板库）
- 设计原则 #6: 更新为三层描述

---

## 测试

### test_schema.py（+10 tests）

| 测试类 | 测试 | 覆盖 |
|--------|------|------|
| `TestShotPlan` | defaults, with_segments, json_round_trip | 基础 CRUD + 序列化 |
| `TestShotResult` | defaults, with_visual, json_round_trip | 基础 CRUD + 视觉产物 + 序列化 |
| `TestScenePlan` | test_backward_compat_segment_ids | 旧 JSON segment_ids → 单 Shot 迁移 |
| `TestSceneResult` | test_backward_compat_segment_ids | 旧 JSON segment_ids/visual → 单 Shot 迁移 |
| `TestScenePlan` | 全部现有测试适配 shots | with_segments, custom_visual_type, json_round_trip, defaults |
| `TestSceneResult` | 全部现有测试适配 shots | with_visual, json_round_trip, defaults |
| `TestPlanManifestWithScenes` | scenes_in_serialization | shots 在序列化后保留 |
| `TestResultManifestWithScenes` | scenes_in_serialization, write_then_read_preserves_scenes | shots 在序列化/写盘后保留 |

### test_rule_planner.py（+1 test）

| 测试 | 覆盖 |
|------|------|
| `test_shot_ids_sequential` | Shot ID 全局递增，跨 Scene 连续 |
| 全部现有测试适配 shots | segment_ids 断言改为 `scene.shots[0].segment_ids` |
