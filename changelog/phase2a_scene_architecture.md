# Phase 2A: Scene 架构 + Rule Planner

**日期**: 2026-04-01
**状态**: 已完成（未提交）

## 概述

引入 Scene（镜头）概念，建立 Segment（TTS 单位）+ Scene（视觉单位）的双层数据模型。Rule Planner 从"逐 segment 设 visual_type"改为"语义分组为 scenes"，Manim Renderer 从扁平 segment 循环重构为按 scene 粒度渲染。

## 核心设计

**Segment vs Scene**：
- Segment 是最小时间单元（一句话），TTS 以 Segment 为单位合成语音
- Scene 是语义单元，由 Planner 将多个 Segment 分组而成，共享同一个视觉方案
- 一个 Scene 包含 1~N 个 Segment，一个 Segment 只属于一个 Scene
- 时间轴上，Scene 的 start/end 由其包含的所有 Segment 的音频时长累加得出

## 修改文件

- `md2video/manifest/schema.py`
- `md2video/core/planner/rule_planner.py`
- `md2video/core/pipeline.py`
- `md2video/tools/render/manim_renderer.py`
- `md2video/assembler/ffmpeg_assembler.py`
- `md2video/config.py`
- `tests/test_rule_planner.py`
- `tests/test_schema.py`
- `TODO.md`

---

## Schema: 新增 ScenePlan / SceneResult

**文件**: `md2video/manifest/schema.py`

### 新增模型

```python
class ScenePlan(BaseModel):
    id: str
    visual_type: str = "text_only"
    visual_params: Dict = Field(default_factory=dict)
    segment_ids: List[str] = Field(default_factory=list)
    section_context: str = ""

class SceneResult(BaseModel):
    id: str
    segment_ids: List[str] = Field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    visual: VisualResult = Field(default_factory=VisualResult)
```

### Manifest 变化

`PlanManifest` 和 `ResultManifest` 各新增 `scenes: List` 字段，默认值为空列表，向后兼容（旧 JSON 不含 `scenes` 字段时自动解析为 `[]`）。

---

## Rule Planner: 语义分组

**文件**: `md2video/core/planner/rule_planner.py`

### 接口变化

```python
# 旧接口 (Phase 1)
def plan(self, segments: List[SegmentPlan]) -> List[SegmentPlan]:
    # 逐 segment 设 visual_type = "text_only"
    return segments

# 新接口 (Phase 2A)
def plan(self, segments: List[SegmentPlan]) -> List[ScenePlan]:
    # 将 segments 分组为 scenes，返回 scene 列表
    return scenes
```

### 分组规则

| 规则 | 描述 |
|------|------|
| R1 | `title_main` / `title_sub` 合并为一个 title scene |
| R2 | `marker_music` / `marker_image` 各自独立成 singleton scene |
| R3 | `section_header` 开启新 scene，并设置 `section_context` |
| R4/R5 | `content` / `appendix` 累积在当前 scene；累计字符超过 `MAX_SCENE_CHARS`（200）时自动拆分 |
| R6 | `explicit=True` 的 segment 独立成 scene，保留其 `visual_type` / `visual_params` |

### 新增函数

`denormalize_scenes_to_segments(segments, scenes)`: 将 scene 的 `visual_type` / `visual_params` 回写到其包含的 non-explicit segments 上，保证下游消费者（Renderer、Assembler）可以直接从 segment 读取视觉信息。

---

## Pipeline: 适配 Scene 粒度

**文件**: `md2video/core/pipeline.py`

### 变化

1. Planner 调用从 `plan.segments = planner.plan(plan.segments)` 改为：
   ```python
   scenes = self.planner.plan(plan.segments)
   denormalize_scenes_to_segments(plan.segments, scenes)
   plan.scenes = scenes
   ```
2. 日志输出从 `N segments` 改为 `N segments, M scenes`
3. TTS 完成后，调用 `_build_scene_results()` 构建 `SceneResult` 列表

### _build_scene_results()

从 segment 的 `start`/`end` 累加出 scene 的 `start`/`end`：
```python
def _build_scene_results(self, scene_plans, segment_results):
    # 每个 scene 的 start = min(其 segments 的 start)
    # 每个 scene 的 end = max(其 segments 的 end)
```

---

## Manim Renderer: 重构为 Scene 粒度

**文件**: `md2video/tools/render/manim_renderer.py`

### 架构变化

原来的 `construct()` 是一个 ~200 行的单体方法。重构后拆分为多个职责清晰的方法：

| 方法 | 职责 |
|------|------|
| `construct()` | 入口，加载 manifest，构建 segment→scene 映射，分发到 flat/scenes 路径 |
| `_construct_flat()` | Phase 1 兼容路径，行为与旧代码完全一致 |
| `_construct_by_scenes()` | Phase 2A 路径，按 scene 循环渲染 |
| `_render_segment()` | 渲染单个 segment（content / section_header / marker） |
| `_render_section_header()` | 左侧字幕堆叠逻辑 |
| `_render_title()` | 标题卡片渲染 |
| `_setup_dot_animation()` | 点动画初始化 + 标题→点变形动画 |
| `_finish()` | 收尾：清除字幕和点动画，保存 timeline |

### 自动兼容

```python
if not plan.scenes:
    self._construct_flat(plan, result)    # Phase 1 旧数据
else:
    self._construct_by_scenes(plan, result, segment_to_scene)  # Phase 2A
```

### 跨 scene 持久状态

原来方法内的局部变量（`timeline`、`current_subtitles`、`is_image_active` 等）提升为 `self.*` 属性，使它们在 `_render_segment()` / `_render_section_header()` 等方法间共享。

---

## FFmpeg Assembler: 预留 Scene 循环

**文件**: `md2video/assembler/ffmpeg_assembler.py`

新增 scene 循环占位代码，当前所有 scene 为 `text_only` 所以是 no-op，为 Phase 2B 的图片叠加做准备：
```python
for scene_plan in self.plan.scenes:
    if scene_plan.visual_type == "text_only":
        continue
    # Phase 2B: 处理 stock_image 等视觉效果
```

---

## Config

**文件**: `md2video/config.py`

```python
MAX_SCENE_CHARS = 200  # 单 scene 内 content 累计字符上限
```

---

## 测试

### test_rule_planner.py（15 tests）

旧测试（5 个 Phase 1 测试）全部删除重写：

| 测试 | 覆盖 |
|------|------|
| `test_basic_grouping` | title 合并 + content 分组 |
| `test_markers_excluded` | marker 不参与内容分组，各自成 singleton |
| `test_section_boundary` | section_header 开启新 scene |
| `test_max_length_split` | 超过 MAX_SCENE_CHARS 自动拆分 |
| `test_explicit_segment_breaks_scene` | explicit segment 中断当前 scene |
| `test_explicit_not_overridden` | explicit 的 visual 不被 planner 覆盖 |
| `test_empty_input` | 空输入返回空列表 |
| `test_all_markers` | 全 marker 输入 |
| `test_section_context_preserved` | section_context 正确传递 |
| `test_image_marker_singleton` | image marker 也是 singleton |
| `test_all_segments_covered` | 每个 segment 恰好出现在一个 scene 中 |
| `test_backward_compat_all_text_only` | 典型输入全部 text_only |
| `test_section_header_alone` | 无 content 的 section_header 独立成 scene |
| `test_appendix_segment` | appendix 与 content 在同一 scene（无 section_header 隔开时） |
| `test_scene_ids_sequential` | scene ID 按 scene_001, scene_002 编号 |

新增 `TestDenormalize` 类（2 tests）：
- `test_copies_visual_to_segments`: scene 的 visual 回写到 segments
- `test_explicit_not_overridden`: explicit segments 不被回写覆盖

### test_schema.py（+11 tests）

| 测试类 | 测试 |
|--------|------|
| `TestScenePlan` | defaults, with_segments, custom_visual_type, json_round_trip |
| `TestSceneResult` | defaults, with_visual, json_round_trip |
| `TestPlanManifestWithScenes` | empty_scenes_default, scenes_in_serialization, backward_compat_no_scenes_field |
| `TestResultManifestWithScenes` | empty_scenes_default, scenes_in_serialization, backward_compat_no_scenes_field, **write_then_read_preserves_scenes** |

---

## Bug 修复：result.json 中 scenes 为空

**文件**: `md2video/core/pipeline.py`

### 现象

`artifacts/result.json` 中 `scenes` 字段为空列表 `[]`，尽管内存中 `result.scenes` 已正确构建。

### 原因

Pipeline 中 `result.json` 的写盘在 `_build_scene_results()` 调用**之前**执行：

```python
# 修复前
result_path.write_text(result.model_dump_json(...))  # 此时 scenes=[]
result.scenes = self._build_scene_results(...)        # 赋值了，但没再写盘
```

### 修复

将 `_build_scene_results()` 移到写盘之前：

```python
# 修复后
result.scenes = self._build_scene_results(...)        # 先构建
result_path.write_text(result.model_dump_json(...))   # 再写盘
```

### 测试补充

`test_schema.py` 新增 `test_write_then_read_preserves_scenes`：模拟 pipeline 写盘→读回流程，验证 scenes 字段在磁盘序列化后不丢失。

---

## TODO.md 更新

- 架构图新增 Scene 概念和双层数据模型标注
- 新增 Section 3.2.1（Scene 定义、动机、与 Segment 的关系、示例）
- Section 3.3: Manifest 增加 Scene 的 Plan/Result 阶段示例和双向关联说明
- Section 3.4: Planner 接口改为 scene-grouping 的输入输出格式
- Section 3.5: 工具按 Audio / Image / Video 三类重组；Manim Render 输入改为 scene 粒度
- 新增 Section 3.7: 时长对齐策略（以 TTS 时长为主轴）
- Section 7: 代码映射表增加 Phase 列
- Section 8: 路线图拆分为 Phase 2A / 2B / 2C，Phase 1 标记已完成
- 新增设计原则 #6: Segment 是 TTS 的单位，Scene 是视觉的单位
