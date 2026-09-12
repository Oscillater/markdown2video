"""A8 组件验收入口（纯 infra CLI，契约即门槛，无人工审核）::

    python -m md2video.check_component <注册模块> [--artifacts DIR] [--timeout N]

流程：显式加载注册模块 → 静态扫描禁用 API（廉价预过滤）→ staged 安装 →
fixture plan（标题 + 三段静默正文，scene 引用该组件、remotion 后端）→
真渲染两遍 → timeline 逐字节比对 + framemd5 逐帧比对（确定性，双跑一致
是「无人审安全性」的来源）→ 黄金帧（首轮存档，复核逐字节比对）→ 全过
提交安装；任一步失败回滚，不留痕。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from md2video.components import install as component_install
from md2video.components.install import install_component, uninstall_component
from md2video.components.registry import (
    get_component,
    load_component_modules,
    registered_components,
    reset_components,
)
from md2video.manifest.schema import ExecutionAssets, PlanManifest, SegmentPlan
from md2video.tools.render.remotion_tool import RemotionRenderTool

# 静态扫描的禁用 API 清单（真正门槛是双跑逐帧一致；这里只为给出更快更好的报错）：
# random / 墙钟时间 / 网络 / 文件系统与进程 / 浏览器存储。
_BANNED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("random", r"Math\.random"),
    ("wall_clock", r"Date\.now|new Date\("),
    ("network", r"\bfetch\(|XMLHttpRequest|WebSocket"),
    (
        "fs_or_process",
        r"require\(|from\s+['\"](node:)?(fs|path|child_process|os|net|http|https)['\"]|process\.env",
    ),
    ("browser_storage", r"localStorage|sessionStorage|document\.cookie"),
)


def _fixture_plan(ref: str) -> PlanManifest:
    """固定验收计划：标题 + 三段静默正文；组件 scene 走 remotion 后端。
    文本与结构永不改（改了会让已存档黄金帧失去可比性）。"""
    return PlanManifest(
        segments=[
            SegmentPlan(id="t1", text="组件验收标题", segment_type="title_main"),
            SegmentPlan(id="s1", text="第一步：准备内容", segment_type="content"),
            SegmentPlan(id="s2", text="第二步：检查闸门", segment_type="content"),
            SegmentPlan(id="s3", text="第三步：交付成片", segment_type="content"),
        ],
        scenes=[{
            "id": "scene_001",
            "visual_type": "text_only",
            "visual_params": {},
            "render_backend": "remotion",
            "component": ref,
            "shots": [{"id": "shot_001", "segment_ids": ["t1", "s1", "s2", "s3"]}],
            "section_context": "check",
        }],
    )


def _fixture_plan_scene_canvas(ref: str) -> PlanManifest:
    """按场挂载（A8.1 场景画布）的固定验收计划。

    与按 shot 夹具的关键差异：组件场被普通场隔开——plan.scenes 里
    scene_001 复现（表示「回到这场」），shot_001 与 shot_003 在成片时间轴
    上不邻接。画布在时间上不连续，状态必须连续：shot_003 的画面要包含
    shot_001 累积的内容（由组件从 scene_shots 时间线纯函数推导）。
    文本与结构永不改（改了会让已存档黄金帧失去可比性）。"""
    return PlanManifest(
        segments=[
            SegmentPlan(id="t1", text="画布验收标题", segment_type="title_main"),
            SegmentPlan(id="s1", text="画布第一笔：坐标系", segment_type="content"),
            SegmentPlan(id="s2", text="中场休息：切到别的画面", segment_type="content"),
            SegmentPlan(id="s3", text="画布第二笔：曲线", segment_type="content"),
        ],
        scenes=[
            {
                "id": "scene_001",
                "visual_type": "text_only",
                "visual_params": {},
                "render_backend": "remotion",
                "component": ref,
                "shots": [{"id": "shot_001", "segment_ids": ["t1", "s1"]}],
                "section_context": "check",
            },
            {
                "id": "scene_002",
                "visual_type": "text_only",
                "visual_params": {},
                "render_backend": "remotion",
                "shots": [{"id": "shot_002", "segment_ids": ["s2"]}],
                "section_context": "check",
            },
            {
                # 回到 scene_001：同 id 复现，shot_003 是画布的第二次「访问」
                "id": "scene_001",
                "visual_type": "text_only",
                "visual_params": {},
                "render_backend": "remotion",
                "component": ref,
                "shots": [{"id": "shot_003", "segment_ids": ["s3"]}],
                "section_context": "check",
            },
        ],
    )


def _framemd5_frame_lines(video_path: Path) -> list[str]:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-f", "framemd5", "-"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"framemd5 failed for {video_path}: {proc.stderr.strip()[-400:]}"
        )
    return [line for line in proc.stdout.splitlines() if "," in line]


def _extract_frame(video_path: Path, timestamp: float, out: Path) -> None:
    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", f"{timestamp:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-y", str(out),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(
            f"frame extraction failed at t={timestamp:.3f}: {proc.stderr.strip()[-400:]}"
        )


def _rollback(ref: str) -> None:
    if component_install.is_installed(ref):
        uninstall_component(ref)
    reset_components()


def verify_component(
    module_name: str, artifacts_dir: Path, *, timeout: int = 300
) -> list[Path]:
    """验收一个表现组件；全过返回黄金帧路径列表（保持安装），失败抛
    RuntimeError（已回滚，不留痕）。"""
    import sys as _sys

    import md2video.components.registry as registry_module

    # 用 spy 捕获模块实际注册的组件（不能靠注册表集合差：已安装组件的
    # 重复注册是幂等的，不产生新条目）。强制重新执行模块，避免缓存。
    registered_refs: list[str] = []
    original_register = registry_module.register_component

    def _spy(component_id, version, kind, component_file, mount="shot"):
        component = original_register(
            component_id, version, kind, component_file, mount
        )
        registered_refs.append(component.ref)
        return component

    _sys.modules.pop(module_name, None)
    registry_module.register_component = _spy
    try:
        load_component_modules(module_name)
    finally:
        registry_module.register_component = original_register

    if len(registered_refs) != 1:
        reset_components()
        raise RuntimeError(
            f"Module {module_name!r} must register exactly one component; "
            f"got {registered_refs or 'none'}"
        )
    ref = registered_refs[0]
    component = get_component(ref)
    assert component is not None

    print(f"[1/6] Static scan: {component.component_file}")
    source = Path(component.component_file).read_text(encoding="utf-8")
    for label, pattern in _BANNED_PATTERNS:
        if re.search(pattern, source):
            reset_components()
            raise RuntimeError(
                f"Banned API detected ({label}): component must render "
                "deterministically from its props (no random/time/network/fs)"
            )

    print(f"[2/6] Staged install: {ref}")
    install_component(component)

    try:
        run_root = Path(artifacts_dir) / "component_check" / ref.replace("@", "_")
        run_root.mkdir(parents=True, exist_ok=True)
        plan = (
            _fixture_plan_scene_canvas(ref)
            if component.mount == "scene"
            else _fixture_plan(ref)
        )
        plan_path = run_root / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        assets_path = run_root / "execution-assets.json"
        assets_path.write_text(
            ExecutionAssets().model_dump_json(indent=2), encoding="utf-8"
        )

        tool = RemotionRenderTool()
        videos: list[Path] = []
        timelines: list[Path] = []
        for run_index in (1, 2):
            print(f"[3/6] Fixture render pass {run_index}/2 (remotion)...")
            out_dir = run_root / f"pass_{run_index}"
            out_dir.mkdir(parents=True, exist_ok=True)
            output = tool.execute({
                "plan_path": str(plan_path),
                "execution_assets_path": str(assets_path),
                "timeline_path": str(out_dir / "timeline.json"),
                "output_dir": str(out_dir),
                "timeout": timeout,
            })
            videos.append(Path(output["video_path"]))
            timelines.append(Path(output["timeline_path"]))

        if timelines[0].read_bytes() != timelines[1].read_bytes():
            raise RuntimeError("Double-run timeline bytes differ")

        print("[4/6] framemd5 frame-by-frame comparison (double-run determinism)...")
        hashes = [_framemd5_frame_lines(video) for video in videos]
        if hashes[0] != hashes[1]:
            raise RuntimeError(
                "Double-run framemd5 mismatch: component rendering is not "
                "deterministic (check for random/time/network access)"
            )

        print("[5/6] Golden frames (first run archives, re-check compares)...")
        props = json.loads(
            (run_root / "pass_1" / "remotion_props.json").read_text(encoding="utf-8")
        )
        body_segments = [
            seg
            for shot in props["shots"]
            for seg in shot["segments"]
            if seg["segment_type"] == "content"
        ]
        timestamps = [0.5] + [
            (seg["start"] + seg["end"]) / 2 for seg in body_segments
        ]
        golden_dir = component_install.REGISTERED_DIR / "golden" / ref
        golden_dir.mkdir(parents=True, exist_ok=True)
        goldens: list[Path] = []
        for index, timestamp in enumerate(timestamps):
            name = f"frame_{index:02d}_t{timestamp:.3f}.png"
            candidate = run_root / name
            _extract_frame(videos[0], timestamp, candidate)
            expected = golden_dir / name
            if expected.is_file():
                if expected.read_bytes() != candidate.read_bytes():
                    raise RuntimeError(
                        f"Golden frame mismatch: {name}; rendering drifted from "
                        "the accepted baseline (environment or component changed)"
                    )
            else:
                shutil.copyfile(candidate, expected)
            goldens.append(expected)

        print(f"[6/6] Committed: {ref} installed with {len(goldens)} golden frames")
        return goldens
    except Exception:
        _rollback(ref)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A8 表现组件验收入口：契约即门槛，无人工审核（全过才安装）",
    )
    parser.add_argument("module", help="组件注册模块（Python 模块路径）")
    parser.add_argument(
        "--artifacts", default="artifacts", help="验收中间产物目录（默认 artifacts/）"
    )
    parser.add_argument("--timeout", type=int, default=300, help="单次渲染超时秒数")
    args = parser.parse_args(argv)

    try:
        goldens = verify_component(
            args.module, Path(args.artifacts), timeout=args.timeout
        )
    except Exception as exc:
        print(f"\nREJECTED: {exc}", file=sys.stderr)
        return 1
    print("\nACCEPTED: component installed")
    for golden in goldens:
        print(f"  golden: {golden}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
