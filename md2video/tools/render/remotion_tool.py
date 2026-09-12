"""RemotionRenderTool — 第二渲染后端（A6 后半）。

契约与 ManimRenderTool 完全一致：JSON input（plan_path /
execution_assets_path / timeline_path / output_dir / timeout）→ 渲染 →
JSON output（video_path / timeline_path / provider / render_dir /
warnings），后端自跑时间不变量闸门。

执行路径：纯函数调度器（remotion_schedule.py）从音频事实 + pack 节奏
推导确定性调度 → 写 props → 复制音频进 public/ → 调 Node 侧 Remotion
CLI 渲染 → ffprobe 校验时长 → 写 timeline.json（同构事实）→ 过闸门。

环境要求：Node 22 + 本目录 `npm install`（remotion 依赖）。依赖缺失时
execute fail fast，注册本身不依赖 Node（与管线“后端未注册开渲前 fail
fast”的约定一致）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from md2video.manifest.schema import ExecutionAssets, PlanManifest
from md2video.timeline.invariants import check_timeline
from md2video.tools.render.manim_renderer_inputs import validate_renderer_inputs
from md2video.tools.render.remotion_schedule import (
    REMOTION_FPS,
    REMOTION_HEIGHT,
    REMOTION_WIDTH,
    build_remotion_schedule,
)

PUBLIC_AUDIO_DIR = "audio"
PROPS_FILENAME = "remotion_props.json"

# 渲染时长与调度时长的容差（秒）：帧取整噪声 + 容器封装余量。
DURATION_TOLERANCE_SECONDS = 0.25


class RemotionRenderTool:
    """Render the base video through the Node-side Remotion composition."""

    def __init__(self, backend_dir: str | Path | None = None):
        self.backend_dir = (
            Path(backend_dir)
            if backend_dir
            else Path(__file__).with_name("remotion_backend")
        )

    @property
    def tool_type(self) -> str:
        return "render"

    @property
    def provider_name(self) -> str:
        return "remotion"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        plan_path = self._required_path(input_data, "plan_path")
        assets_path = self._required_path(input_data, "execution_assets_path")
        timeline_path = Path(self._required_value(input_data, "timeline_path"))
        output_dir = Path(input_data.get("output_dir", timeline_path.parent))
        timeout = int(input_data.get("timeout", 300))

        if not plan_path.exists():
            raise FileNotFoundError(f"Plan manifest not found: {plan_path}")
        if not assets_path.exists():
            raise FileNotFoundError(f"Execution assets not found: {assets_path}")

        plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
        assets = ExecutionAssets.model_validate_json(
            assets_path.read_text(encoding="utf-8")
        )
        validate_renderer_inputs(plan, assets)

        output_dir.mkdir(parents=True, exist_ok=True)
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        if timeline_path.exists():
            timeline_path.unlink()

        pack = self._active_style_pack()
        schedule, warnings = build_remotion_schedule(
            plan, assets, pack, width=REMOTION_WIDTH, height=REMOTION_HEIGHT, fps=REMOTION_FPS
        )
        warnings = list(warnings)

        props = self._materialize_audio_assets(schedule, output_dir)
        props_path = output_dir / PROPS_FILENAME
        props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

        video_path = self._run_remotion_render(
            props_path, output_dir, timeout=timeout
        )

        # 时间事实落盘（与 manim 后端同构），并过同一道时间不变量闸门
        timeline_path.write_text(
            json.dumps(schedule["timeline"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        check = check_timeline(plan, assets, json.loads(timeline_path.read_text(encoding="utf-8")))
        if not check.ok:
            raise RuntimeError(
                f"Timeline invariant violations in {timeline_path}: "
                + " | ".join(check.errors)
            )
        warnings.extend(check.warnings)

        self._validate_video_duration(video_path, float(schedule["duration"]))

        return {
            "video_path": str(video_path),
            "timeline_path": str(timeline_path),
            "provider": self.provider_name,
            "render_dir": str(self.backend_dir),
            "warnings": warnings,
        }

    # ---- 内部步骤 ----

    def _active_style_pack(self):
        from md2video.style.packs import active_pack

        return active_pack()[1]

    def _materialize_audio_assets(
        self, schedule: dict[str, Any], output_dir: Path
    ) -> dict[str, Any]:
        """复制音频进 public/audio 并把 props 的 audio_path 改写为 public 相对路径。"""
        public_dir = self.backend_dir / "public" / PUBLIC_AUDIO_DIR
        public_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        for shot in schedule.get("shots", []):
            for segment in shot.get("segments", []):
                source = segment.get("audio_path") or ""
                if not source:
                    continue
                source_path = Path(source)
                stem = source_path.stem or "audio"
                candidate = f"{stem}{source_path.suffix}"
                suffix = 1
                while candidate in used_names:
                    candidate = f"{stem}_{suffix}{source_path.suffix}"
                    suffix += 1
                used_names.add(candidate)
                target = public_dir / candidate
                if not target.exists():
                    shutil.copy2(source_path, target)
                segment["audio_path"] = f"{PUBLIC_AUDIO_DIR}/{candidate}"
        return schedule

    def _run_remotion_render(
        self, props_path: Path, output_dir: Path, *, timeout: int
    ) -> Path:
        npx = shutil.which("npx")
        if npx is None:
            raise RuntimeError(
                "npx not found on PATH; Remotion backend requires Node.js 22+"
            )
        if not (self.backend_dir / "node_modules").exists():
            raise RuntimeError(
                "Remotion backend dependencies missing; run `npm install` in "
                f"{self.backend_dir}"
            )
        # 子进程 cwd 是 backend_dir：调用方传入的相对路径必须先按当前进程
        # cwd 解析成绝对路径，否则 Remotion 会在 backend_dir 下找 props、
        # 把视频写到错误的目录。
        props_path = props_path.resolve()
        video_path = (output_dir / "base_remotion.mp4").resolve()
        cmd = [
            npx,
            "remotion",
            "render",
            "src/index.ts",
            "Md2VideoMain",
            str(video_path),
            "--props",
            str(props_path),
            "--codec",
            "h264",
            "--audio-codec",
            "aac",
            "--log",
            "error",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(self.backend_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
            if stderr_tail:
                print("  Remotion stderr (last 20 lines):")
                for line in stderr_tail.splitlines():
                    print(f"    {line}")
            raise RuntimeError(f"Remotion rendering failed (exit {proc.returncode})")
        if not video_path.exists():
            raise FileNotFoundError("Remotion render produced no video")
        print("  Render OK (remotion)")
        return video_path

    def _validate_video_duration(self, video_path: Path, expected: float) -> None:
        actual = self._probe_duration(video_path)
        if actual is None:
            raise RuntimeError(f"Could not probe rendered video duration: {video_path}")
        if abs(actual - expected) > DURATION_TOLERANCE_SECONDS:
            raise RuntimeError(
                f"Rendered duration {actual:.3f}s deviates from schedule "
                f"{expected:.3f}s beyond tolerance"
            )

    @staticmethod
    def _probe_duration(video_path: Path) -> float | None:
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            return float(proc.stdout.strip())
        except ValueError:
            return None

    @staticmethod
    def _required_value(input_data: Dict[str, Any], key: str) -> str:
        value = input_data.get(key)
        if not value:
            raise ValueError(f"RemotionRenderTool requires input field: {key}")
        return str(value)

    @classmethod
    def _required_path(cls, input_data: Dict[str, Any], key: str) -> Path:
        return Path(cls._required_value(input_data, key))


def _now() -> float:
    import time

    return time.time()
