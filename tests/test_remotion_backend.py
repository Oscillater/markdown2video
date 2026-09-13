"""A6 后半 Remotion 后端测试：调度器时序语义 + 渲染工具契约。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from md2video.config import ToolConfig
from md2video.core.pipeline import Pipeline
from md2video.manifest.schema import (
    AudioRequest,
    AudioAsset,
    ExecutionAssets,
    PlanManifest,
    SegmentPlan,
)
from md2video.style.packs import get_pack
from md2video.timeline.invariants import check_timeline
from md2video.tools.render.remotion_schedule import (
    REVEAL_CAPABILITIES,
    build_remotion_schedule,
    style_payload,
)
from md2video.tools.render.remotion_tool import RemotionRenderTool


def _plan(segments: list[SegmentPlan], shots: list[dict]) -> PlanManifest:
    return PlanManifest(
        segments=segments,
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "shots": shots,
            "section_context": "test",
        }],
        media_declarations={},
    )


def _silent_segment(seg_id: str, seg_type: str = "content") -> SegmentPlan:
    return SegmentPlan(id=seg_id, text=f"文本 {seg_id}", segment_type=seg_type, audio_request=None)


def _voiced_segment(seg_id: str) -> SegmentPlan:
    return SegmentPlan(
        id=seg_id,
        text=f"朗读 {seg_id}",
        segment_type="content",
        audio_request=AudioRequest(),
    )


def _assets_with_audio(*pairs: tuple[str, float]) -> ExecutionAssets:
    return ExecutionAssets(
        audio_assets=[
            AudioAsset(
                segment_id=seg_id,
                path=f"audio/{seg_id}.mp3",
                duration=duration,
                provider="edge-tts",
                cache_key=f"key-{seg_id}",
            )
            for seg_id, duration in pairs
        ],
    )


# ==================== 调度器 ====================


def test_silent_segments_use_pack_pace_and_sequence():
    plan = _plan(
        [_silent_segment("s1"), _silent_segment("s2")],
        [
            {"id": "shot_001", "segment_ids": ["s1"]},
            {"id": "shot_002", "segment_ids": ["s2"]},
        ],
    )
    pack = get_pack()
    schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), pack)

    assert schedule["duration"] == pytest.approx(4.0)  # 2 x body pace (2.0)
    shots = schedule["shots"]
    assert [s["shot_id"] for s in shots] == ["shot_001", "shot_002"]
    assert shots[0]["start"] == 0.0 and shots[0]["end"] == 2.0
    assert shots[1]["start"] == 2.0 and shots[1]["end"] == 4.0
    assert shots[0]["segment_ids"] == ["s1"]

    text = schedule["timeline"]["text"]
    assert [(t["start"], t["end"]) for t in text] == [(0.0, 2.0), (2.0, 4.0)]
    assert all(t["end"] is not None for t in text)


def test_voiceover_duration_comes_from_audio_fact():
    plan = _plan([_voiced_segment("v1")], [{"id": "shot_001", "segment_ids": ["v1"]}])
    assets = _assets_with_audio(("v1", 3.27))
    schedule, _ = build_remotion_schedule(plan, assets, get_pack())

    assert schedule["duration"] == pytest.approx(3.27)
    assert schedule["shots"][0]["segments"][0]["audio_path"] == "audio/v1.mp3"
    # 时间事实与音频事实一致 → 不触发朗读差值告警
    check = check_timeline(plan, assets, schedule["timeline"])
    assert check.ok
    assert not check.warnings


def test_title_card_leads_and_uses_title_hold():
    plan = _plan(
        [
            SegmentPlan(id="t1", text="主标题", segment_type="title_main", audio_request=None),
            SegmentPlan(id="s1", text="正文", segment_type="content", audio_request=None),
        ],
        [
            {"id": "shot_001", "segment_ids": ["t1", "s1"]},
        ],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    # 标题 pass 先行（title_hold=1.0），正文随后在同一 shot 内继续
    assert schedule["duration"] == pytest.approx(1.0 + 2.0)
    shots = schedule["shots"]
    assert len(shots) == 1
    assert shots[0]["start"] == 0.0 and shots[0]["end"] == 3.0
    assert shots[0]["segment_ids"] == ["t1", "s1"]

    text = {t["segment_id"]: t for t in schedule["timeline"]["text"]}
    assert text["t1"]["start"] == 0.0 and text["t1"]["end"] == 3.0  # 标题全程可见
    assert text["s1"]["start"] == 1.0 and text["s1"]["end"] == 3.0

    assert schedule["title"] is not None
    assert {seg["segment_id"] for seg in schedule["title"]["segments"]} == {"t1"}


def test_title_payload_carries_retreat_end():
    """标题退场（A）：title payload 携带 end = 第一个正文镜头的开始
    （title_hold），wrapper 据此在片头淡出标题卡。"""
    plan = _plan(
        [
            SegmentPlan(id="t1", text="主标题", segment_type="title_main", audio_request=None),
            SegmentPlan(id="s1", text="正文", segment_type="content", audio_request=None),
        ],
        [
            {"id": "shot_001", "segment_ids": ["t1", "s1"]},
        ],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    assert schedule["title"]["end"] == pytest.approx(1.0)
    # 第一个正文镜头（含标题与正文的 shot）从 title_hold 开始
    assert schedule["shots"][0]["start"] == 0.0


def test_title_only_shot_closes_at_title_hold():
    plan = _plan(
        [SegmentPlan(id="t1", text="主标题", segment_type="title_main", audio_request=None)],
        [{"id": "shot_001", "segment_ids": ["t1"]}],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())
    assert schedule["duration"] == pytest.approx(1.0)
    assert schedule["shots"][0]["end"] == pytest.approx(1.0)


def test_section_header_stacks_and_closes_on_replacement():
    plan = _plan(
        [_silent_segment("h1", "section_header"), _silent_segment("h2", "section_header")],
        [{"id": "shot_001", "segment_ids": ["h1", "h2"]}],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    text = {t["segment_id"]: t for t in schedule["timeline"]["text"]}
    # h1 被 h2 顶掉（section_header pace 0.5）
    assert text["h1"]["start"] == 0.0 and text["h1"]["end"] == 0.5
    assert text["h2"]["start"] == 0.5 and text["h2"]["end"] == 1.0


def test_marker_cues_recorded_without_consuming_time():
    plan = _plan(
        [_silent_segment("s1")],
        [{
            "id": "shot_001",
            "segment_ids": ["s1"],
            "cues": [
                {"id": "cue_bgm_start", "cue_type": "marker_music", "kind": "start", "name": "bgm", "position": "start"},
                {"id": "cue_bgm_end", "cue_type": "marker_music", "kind": "end", "name": "bgm", "position": "end"},
            ],
        }],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    assert schedule["duration"] == pytest.approx(2.0)  # cue 不消耗时间
    markers = {m["id"]: m for m in schedule["timeline"]["markers"]}
    assert markers["cue_bgm_start"]["time"] == 0.0
    assert markers["cue_bgm_end"]["time"] == 2.0
    assert markers["cue_bgm_start"]["cue_type"] == "marker_music"


def test_before_and_after_marker_cues_reach_timeline():
    """真实 markdown 的 [image_start]/[image_end]/[music_*] 走 before/after 锚点
    cue：必须落进 timeline markers（锚前=段起点、锚后=段终点），否则装配器
    的图片/BGM 条目为空、时间闸门直接拒绝。"""
    plan = _plan(
        [_silent_segment("s1"), _silent_segment("s2")],
        [{
            "id": "shot_001",
            "segment_ids": ["s1", "s2"],
            "cues": [
                {"id": "cue_img_start", "cue_type": "marker_image", "kind": "start",
                 "name": "cover", "position": "before", "anchor_segment_id": "s1"},
                {"id": "cue_img_end", "cue_type": "marker_image", "kind": "end",
                 "name": "cover", "position": "after", "anchor_segment_id": "s2"},
            ],
        }],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    assert schedule["duration"] == pytest.approx(4.0)  # cue 不消耗时间
    markers = {m["id"]: m for m in schedule["timeline"]["markers"]}
    assert set(markers) == {"cue_img_start", "cue_img_end"}
    assert markers["cue_img_start"]["time"] == pytest.approx(0.0)  # s1 段起点
    assert markers["cue_img_end"]["time"] == pytest.approx(4.0)    # s2 段终点
    for marker in markers.values():
        assert not any(k.startswith("_") for k in marker), marker
    check = check_timeline(plan, ExecutionAssets(), schedule["timeline"])
    assert check.ok, check.errors


def test_unanchored_after_marker_clings_to_own_shot_end():
    """锚点段不在正文 pass（如锚在标题段）：marker 挂回 cue 所属 shot 末端，
    不得用全片末端撞碎非末尾 shot 的闸门区间约束。"""
    plan = _plan(
        [
            SegmentPlan(id="t1", text="主标题", segment_type="title_main", audio_request=None),
            _silent_segment("s1"),
        ],
        [
            {"id": "shot_001", "segment_ids": ["t1"]},
            {"id": "shot_002", "segment_ids": ["s1"], "cues": [
                {"id": "cue_orphan", "cue_type": "marker_image", "kind": "start",
                 "name": "cover", "position": "after", "anchor_segment_id": "t1"},
            ]},
        ],
    )
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    markers = {m["id"]: m for m in schedule["timeline"]["markers"]}
    # title_hold 1.0 + body 2.0；shot_002 = [1.0, 3.0]，marker 挂 shot 末端
    assert markers["cue_orphan"]["time"] == pytest.approx(3.0)
    check = check_timeline(plan, ExecutionAssets(), schedule["timeline"])
    assert check.ok, check.errors


def test_timeline_facts_pass_invariants_gate():
    plan = _plan(
        [_voiced_segment("v1"), _silent_segment("s1")],
        [
            {"id": "shot_001", "segment_ids": ["v1"]},
            {"id": "shot_002", "segment_ids": ["s1"]},
        ],
    )
    assets = _assets_with_audio(("v1", 1.4))
    schedule, _ = build_remotion_schedule(plan, assets, get_pack())
    check = check_timeline(plan, assets, schedule["timeline"])
    assert check.ok


def test_layout_regions_payload_is_pixel_rects():
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    schedule, _ = build_remotion_schedule(plan, ExecutionAssets(), get_pack())
    regions = schedule["shots"][0]["regions"]
    assert regions
    for rect in regions.values():
        left, top, w, h = rect
        assert 0 <= left and 0 <= top
        assert w > 0 and h > 0
        assert left + w <= schedule["width"]
        assert top + h <= schedule["height"]


def test_style_payload_degrades_unknown_capabilities():
    pack = get_pack().model_copy(deep=True)
    pack.motion.title_reveal = "explosion"  # 不认识的意图
    pack.motif.kind = "fireworks"  # 不认识的母题
    style, warnings = style_payload(pack)
    assert style["motion"]["title_reveal"] == "appear"
    assert style["motif"]["kind"] == ""
    assert len(warnings) == 2
    known = {name for name in REVEAL_CAPABILITIES}
    assert style["motion"]["body_reveal"] in known


# ==================== 渲染工具 ====================


def _write_plan_and_assets(tmp_path: Path, voiced: bool = False):
    segment = (
        SegmentPlan(
            id="v1",
            text="朗读",
            segment_type="content",
            audio_request=AudioRequest(),
        )
        if voiced
        else _silent_segment("s1")
    )
    plan = PlanManifest(
        segments=[segment],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "shots": [{"id": "shot_001", "segment_ids": [segment.id]}],
            "section_context": "t",
        }],
        media_declarations={},
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    audio_path = None
    if voiced:
        audio_path = tmp_path / "v1.mp3"
        audio_path.write_bytes(b"fake audio")
        assets = ExecutionAssets(
            audio_assets=[AudioAsset(segment_id="v1", path=str(audio_path), duration=1.5)],
        )
    else:
        assets = ExecutionAssets()
    assets_path = tmp_path / "execution-assets.json"
    assets_path.write_text(assets.model_dump_json(indent=2), encoding="utf-8")
    return plan_path, assets_path, audio_path


class _FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_remotion_tool_execute_contract(tmp_path):
    plan_path, assets_path, _ = _write_plan_and_assets(tmp_path)
    output_dir = tmp_path / "run"
    output_dir.mkdir()

    tool = RemotionRenderTool()

    def fake_run(cmd, **kwargs):
        # 渲染命令：[npx, remotion, render, entry, comp-id, video_path, ...]
        # ffprobe 命令返回调度时长
        if cmd[1] == "remotion":
            video_path = Path(cmd[5])
            video_path.write_bytes(b"fake mp4")
            return _FakeProcess(0)
        return _FakeProcess(0, stdout="2.0\n")

    with (
        patch("shutil.which", return_value="C:/fake/npx.cmd"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        output = tool.execute({
            "plan_path": str(plan_path),
            "execution_assets_path": str(assets_path),
            "timeline_path": str(output_dir / "timeline.json"),
            "output_dir": str(output_dir),
        })

    assert output["provider"] == "remotion"
    assert output["video_path"] == str(output_dir / "base_remotion.mp4")
    assert Path(output["timeline_path"]).exists()
    assert (output_dir / "remotion_props.json").exists()

    timeline = json.loads(Path(output["timeline_path"]).read_text(encoding="utf-8"))
    assert timeline["shots"][0]["segment_ids"] == ["s1"]

    props = json.loads((output_dir / "remotion_props.json").read_text(encoding="utf-8"))
    assert props["version"] == "remotion.v1"
    assert props["timeline"]["shots"][0]["shot_id"] == "shot_001"


def test_remotion_tool_resolves_relative_paths_against_caller_cwd(tmp_path, monkeypatch):
    """子进程 cwd 是 backend_dir：相对 output_dir 必须按调用方 cwd 解析成
    绝对路径传给 Remotion CLI，否则 props 找不到、视频写错目录。"""
    plan_path, assets_path, _ = _write_plan_and_assets(tmp_path)
    monkeypatch.chdir(tmp_path)
    tool = RemotionRenderTool()

    seen: dict[str, Path] = {}

    def fake_run(cmd, **kwargs):
        if cmd[1] == "remotion":
            seen["video"] = Path(cmd[5])
            seen["props"] = Path(cmd[7])
            seen["video"].write_bytes(b"fake mp4")
            return _FakeProcess(0)
        return _FakeProcess(0, stdout="2.0\n")

    with (
        patch("shutil.which", return_value="C:/fake/npx.cmd"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        output = tool.execute({
            "plan_path": str(plan_path),
            "execution_assets_path": str(assets_path),
            "timeline_path": "run/timeline.json",
            "output_dir": "run",
        })

    assert seen["video"].is_absolute()
    assert seen["props"].is_absolute()
    assert seen["props"].read_text(encoding="utf-8").startswith("{")
    assert Path(output["video_path"]).is_absolute()
    assert Path(output["video_path"]).exists()


def test_remotion_tool_copies_audio_into_public(tmp_path):
    plan_path, assets_path, audio_path = _write_plan_and_assets(tmp_path, voiced=True)
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    tool = RemotionRenderTool()

    def fake_run(cmd, **kwargs):
        if cmd[1] == "remotion":
            Path(cmd[5]).write_bytes(b"fake mp4")
            return _FakeProcess(0)
        return _FakeProcess(0, stdout="1.5\n")

    with (
        patch("shutil.which", return_value="C:/fake/npx.cmd"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        output = tool.execute({
            "plan_path": str(plan_path),
            "execution_assets_path": str(assets_path),
            "timeline_path": str(output_dir / "timeline.json"),
            "output_dir": str(output_dir),
        })

    props = json.loads((output_dir / "remotion_props.json").read_text(encoding="utf-8"))
    audio_rel = props["shots"][0]["segments"][0]["audio_path"]
    assert audio_rel.startswith("audio/")
    assert (tool.backend_dir / "public" / audio_rel).read_bytes() == b"fake audio"
    assert Path(output["timeline_path"]).exists()


def test_remotion_tool_fails_fast_without_node_modules(tmp_path):
    plan_path, assets_path, _ = _write_plan_and_assets(tmp_path)
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    tool = RemotionRenderTool()

    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="npx not found"):
            tool.execute({
                "plan_path": str(plan_path),
                "execution_assets_path": str(assets_path),
                "timeline_path": str(output_dir / "timeline.json"),
                "output_dir": str(output_dir),
            })


def test_pipeline_registers_remotion_backend(tmp_path):
    with patch.object(Pipeline, "_create_planner"):
        pipeline = Pipeline(artifacts_dir=tmp_path, tool_config=ToolConfig())
    tool = pipeline.registry.get_tool("render", "remotion")
    assert isinstance(tool, RemotionRenderTool)
    assert tool.tool_type == "render"


# ==================== A8 表现组件 ====================


def test_schedule_carries_installed_component_ref(tmp_path, monkeypatch):
    """scene 声明且已安装的组件 → 调度 payload 带 component 字段，无 warning。"""
    from md2video.components import install as install_mod
    from md2video.components.registry import (
        register_component,
        reset_components,
    )

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tsx = src_dir / "tmp_step.tsx"
    tsx.write_text("export default 1;\n", encoding="utf-8")
    component = register_component("tmp_step", "1.0.0", "body", tsx)
    install_mod.install_component(component)
    try:
        plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
        plan.scenes[0].component = "tmp_step@1.0.0"
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

        assert schedule["shots"][0]["component"] == "tmp_step@1.0.0"
        assert warnings == []
    finally:
        reset_components()


def test_schedule_passes_visual_params_to_component_scene(tmp_path, monkeypatch):
    """plan 作者的 scene 级编排数据（visual_params）随组件场下发，
    非组件场不带该字段（既有 payload 形状零变化）。"""
    from md2video.components import install as install_mod
    from md2video.components.registry import (
        register_component,
        reset_components,
    )

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tsx = src_dir / "tmp_step.tsx"
    tsx.write_text("export default 1;\n", encoding="utf-8")
    component = register_component("tmp_step", "1.0.0", "body", tsx)
    install_mod.install_component(component)
    try:
        plan = PlanManifest(
            segments=[_silent_segment("s1"), _silent_segment("s2")],
            scenes=[
                {
                    "id": "scene_001",
                    "visual_type": "text_only",
                    "visual_params": {"layers": [{"shot": "shot_001", "kind": "sine"}]},
                    "component": "tmp_step@1.0.0",
                    "shots": [{"id": "shot_001", "segment_ids": ["s1"]}],
                    "section_context": "test",
                },
                {
                    "id": "scene_002",
                    "visual_type": "text_only",
                    "visual_params": {"unrelated": True},
                    "shots": [{"id": "shot_002", "segment_ids": ["s2"]}],
                    "section_context": "test",
                },
            ],
            media_declarations={},
        )
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

        assert warnings == []
        assert schedule["shots"][0]["visual_params"] == {
            "layers": [{"shot": "shot_001", "kind": "sine"}]
        }
        assert "visual_params" not in schedule["shots"][1]
    finally:
        reset_components()


def test_schedule_degrades_registered_but_not_installed_component(tmp_path):
    """已注册但未安装（env 开发期加载）→ 不下发 ref + warning，不静默落
    到 Node 缺省。"""
    from md2video.components.registry import register_component, reset_components

    tsx = tmp_path / "demo.tsx"
    tsx.write_text("export default 1;\n", encoding="utf-8")
    register_component("demo_comp", "1.0.0", "body", tsx)
    try:
        plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
        plan.scenes[0].component = "demo_comp@1.0.0"
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())
    finally:
        reset_components()

    assert "component" not in schedule["shots"][0]
    assert any("demo_comp@1.0.0" in w and "not installed" in w for w in warnings)


def test_schedule_degrades_unknown_component_with_warning():
    """未知组件 id → payload 不带 component 字段（Node 走默认渲染）+ warning。"""
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    plan.scenes[0].component = "ghost@1.0.0"

    schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    assert "component" not in schedule["shots"][0]
    assert any("ghost@1.0.0" in w and "not registered" in w for w in warnings)


def test_schedule_omits_component_for_plain_scenes():
    """无组件 scene 的 payload 与既有形状完全一致（字段缺省，不改 props）。"""
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

    assert "component" not in schedule["shots"][0]
    assert warnings == []


# ==================== A8.1 场景画布（按场挂载） ====================


def _install_canvas_component(tmp_path, monkeypatch, mount="scene"):
    """注册并安装一个临时组件，返回 ref；测试结束自动清理注册表。

    id 随 mount 区分：注册表跨测试残留（reset 会在 monkeypatched 目录上
    重载），同 id 异内容会 fail fast。"""
    from md2video.components import install as install_mod
    from md2video.components.registry import register_component

    component_id = f"tmp_canvas_{mount}"
    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tsx = src_dir / "tmp_canvas.tsx"
    tsx.write_text("export default 1;\n", encoding="utf-8")
    component = register_component(component_id, "1.0.0", "body", tsx, mount=mount)
    install_mod.install_component(component)
    return component.ref


def test_scene_canvas_shots_carry_full_scene_timeline(tmp_path, monkeypatch):
    """按场挂的组件：每个 shot 实例携带本场全部镜头时间线 + 自己排第几。"""
    from md2video.components.registry import reset_components

    ref = _install_canvas_component(tmp_path, monkeypatch, mount="scene")
    try:
        plan = _plan(
            [_silent_segment("s1"), _silent_segment("s2")],
            [{"id": "shot_001", "segment_ids": ["s1"]}, {"id": "shot_002", "segment_ids": ["s2"]}],
        )
        plan.scenes[0].component = ref
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

        assert warnings == []
        first, second = schedule["shots"]
        assert first["scene_shot_index"] == 0
        assert second["scene_shot_index"] == 1
        assert [s["shot_id"] for s in first["scene_shots"]] == ["shot_001", "shot_002"]
        # 时间线里的镜头窗口按调度顺序递增，且带各自的正文段
        assert first["scene_shots"][0]["start"] < first["scene_shots"][1]["start"]
        assert first["scene_shots"][1]["segments"][0]["segment_id"] == "s2"
        # 第二个实例能看到第一个镜头的窗口事实（状态累积的输入）
        assert second["scene_shots"][0]["shot_id"] == "shot_001"
        # timeline 事实保持精简：不携带 scene_shots（那只是组件 props）
        for shot in schedule["timeline"]["shots"]:
            assert "scene_shots" not in shot
    finally:
        reset_components()


def test_scene_canvas_spans_revisit_scenes(tmp_path, monkeypatch):
    """scene 复现（同一 id 在 plan.scenes 出现两次 = 回到这场）：画布时间线
    收拢两次访问的镜头，按时间排序；中间普通场不受影响。"""
    from md2video.components.registry import reset_components

    ref = _install_canvas_component(tmp_path, monkeypatch, mount="scene")
    try:
        plan = PlanManifest(
            segments=[
                _silent_segment("s1"),
                _silent_segment("s2"),
                _silent_segment("s3"),
            ],
            scenes=[
                {
                    "id": "scene_001",
                    "visual_type": "text_only",
                    "visual_params": {},
                    "component": ref,
                    "shots": [{"id": "shot_001", "segment_ids": ["s1"]}],
                    "section_context": "test",
                },
                {
                    "id": "scene_002",
                    "visual_type": "text_only",
                    "visual_params": {},
                    "shots": [{"id": "shot_002", "segment_ids": ["s2"]}],
                    "section_context": "test",
                },
                {
                    # 回到 scene_001：散开镜头是合法用法，不加连续性检查
                    "id": "scene_001",
                    "visual_type": "text_only",
                    "visual_params": {},
                    "component": ref,
                    "shots": [{"id": "shot_003", "segment_ids": ["s3"]}],
                    "section_context": "test",
                },
            ],
            media_declarations={},
        )
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

        assert warnings == []
        assert len(schedule["shots"]) == 3
        first_visit, middle, second_visit = schedule["shots"]
        # 组件场：两个访问实例拿到同一条全场时间线（跨 scene 复现收拢）
        assert [s["shot_id"] for s in first_visit["scene_shots"]] == ["shot_001", "shot_003"]
        assert second_visit["scene_shots"] == first_visit["scene_shots"]
        assert first_visit["scene_shot_index"] == 0
        assert second_visit["scene_shot_index"] == 1
        assert first_visit["start"] < second_visit["start"]  # 时间上被隔开
        # 普通场：无组件字段、无场景画布字段
        assert "component" not in middle
        assert "scene_shots" not in middle
    finally:
        reset_components()


def test_shot_mounted_component_gets_no_scene_timeline(tmp_path, monkeypatch):
    """按 shot 挂的组件（默认）：payload 不带场景画布字段，行为与 A8 一致。"""
    from md2video.components.registry import reset_components

    ref = _install_canvas_component(tmp_path, monkeypatch, mount="shot")
    try:
        plan = _plan(
            [_silent_segment("s1"), _silent_segment("s2")],
            [{"id": "shot_001", "segment_ids": ["s1"]}, {"id": "shot_002", "segment_ids": ["s2"]}],
        )
        plan.scenes[0].component = ref
        schedule, warnings = build_remotion_schedule(plan, ExecutionAssets(), get_pack())

        assert warnings == []
        for shot in schedule["shots"]:
            assert shot["component"] == ref
            assert "scene_shots" not in shot
            assert "scene_shot_index" not in shot
    finally:
        reset_components()


def _pipeline_with_planner_stub(tmp_path: Path) -> Pipeline:
    with patch.object(Pipeline, "_create_planner"):
        return Pipeline(artifacts_dir=tmp_path, tool_config=ToolConfig())


def test_pipeline_component_validation_fails_fast_on_wrong_backend(tmp_path):
    """组件声明在 manim scene 上 = 显式选择无法满足 → fail fast，不静默丢弃。"""
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    plan.scenes[0].component = "step_list@1.0.0"  # 未指定 render_backend → manim
    pipeline = _pipeline_with_planner_stub(tmp_path)

    with pytest.raises(ValueError, match="require remotion"):
        pipeline._validate_plan_components(plan)


def test_pipeline_component_validation_fails_fast_on_malformed_ref(tmp_path):
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    plan.scenes[0].component = "step_list"  # 缺 @version
    plan.scenes[0].render_backend = "remotion"
    pipeline = _pipeline_with_planner_stub(tmp_path)

    with pytest.raises(ValueError, match="Invalid component ref"):
        pipeline._validate_plan_components(plan)


def test_pipeline_component_validation_accepts_remotion_scene_with_unknown_id(tmp_path):
    """格式合法 + remotion 后端 → 校验通过；未注册 id 的降级在渲染层 + warning。"""
    plan = _plan([_silent_segment("s1")], [{"id": "shot_001", "segment_ids": ["s1"]}])
    plan.scenes[0].component = "not_yet_registered@1.0.0"
    plan.scenes[0].render_backend = "remotion"
    pipeline = _pipeline_with_planner_stub(tmp_path)

    pipeline._validate_plan_components(plan)


def test_pipeline_loads_component_modules_on_init(tmp_path, monkeypatch):
    """env MD2VIDEO_COMPONENTS 指向注册模块 → Pipeline 启动时显式加载；
    模块不存在 → 启动即 fail fast，不带病开渲。"""
    from md2video.components.registry import COMPONENTS_ENV, get_component

    (tmp_path / "demo.tsx").write_text("export default 1;\n", encoding="utf-8")
    (tmp_path / "cmp_reg_pipeline.py").write_text(
        "from md2video.components.registry import register_component\n"
        "register_component('demo', '1.0.0', 'body', 'demo.tsx')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(COMPONENTS_ENV, "cmp_reg_pipeline")

    with patch.object(Pipeline, "_create_planner"):
        Pipeline(artifacts_dir=tmp_path / "artifacts", tool_config=ToolConfig())
    assert get_component("demo@1.0.0") is not None

    from md2video.components.registry import reset_components
    reset_components()

    monkeypatch.setenv(COMPONENTS_ENV, "no_such_component_module_xyz")
    with patch.object(Pipeline, "_create_planner"):
        with pytest.raises(ModuleNotFoundError):
            Pipeline(artifacts_dir=tmp_path / "artifacts", tool_config=ToolConfig())
