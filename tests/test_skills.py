"""Skill packaging, shared launcher, examples, and opt-in offline render checks."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
import wave

import pytest

from md2video.components.registry import get_component, is_installed
from md2video.manifest.migration import load_plan_manifest_json
from md2video.manifest.schema import AudioAsset, ExecutionAssets
from md2video.style.packs import ink_night
from md2video.timeline.invariants import check_timeline
from md2video.tools.cache import ToolCache
from md2video.tools.render.remotion_schedule import build_remotion_schedule


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
LAUNCHER = SKILLS / "md2video/scripts/run.py"
EXAMPLES = [
    SKILLS / "md2video-tech-explainer/examples/cache.plan.json",
    SKILLS / "md2video-math-explainer/examples/unit-circle.plan.json",
]


def load_launcher():
    spec = importlib.util.spec_from_file_location("skill_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_plan(path):
    plan, warnings = load_plan_manifest_json(path.read_text(encoding="utf-8"))
    assert not warnings
    return plan


def test_three_skills_have_standard_frontmatter_and_names():
    paths = sorted(SKILLS.glob("*/SKILL.md"))
    assert [p.parent.name for p in paths] == [
        "md2video", "md2video-math-explainer", "md2video-tech-explainer",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        frontmatter, body = text[4:].split("\n---\n", 1)
        fields = dict(line.split(": ", 1) for line in frontmatter.splitlines())
        assert fields["name"] == path.parent.name
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"])
        assert len(fields["name"]) <= 64
        assert 0 < len(fields["description"]) <= 1024
        assert len(fields["compatibility"]) <= 500
        assert body.strip()


def test_project_registers_repo_skills_without_machine_specific_paths():
    settings = ROOT / ".pi/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data == {"skills": ["../skills"]}
    assert (settings.parent / data["skills"][0]).resolve() == SKILLS


def test_skill_markdown_links_resolve_and_run_commands_use_shared_launcher():
    for path in SKILLS.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            target = target.split("#", 1)[0]
            assert (path.parent / target).resolve().exists(), (path, target)
        assert not re.search(r"(?m)^python -m md2video", text), path
    for name in ("md2video-tech-explainer", "md2video-math-explainer"):
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        for shared in ("runtime.md", "plan.md", "components.md"):
            assert f"../md2video/references/{shared}" in text


def test_launcher_options_stay_in_sync_with_core_cli():
    module = load_launcher()
    tree = ast.parse((ROOT / "md2video/cli.py").read_text(encoding="utf-8"))
    cli_flags = {
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        and arg.value.startswith("-")
    }
    helper_flags = {
        flag for action in module.build_parser()._actions
        for flag in action.option_strings if flag not in ("-h", "--help")
    }
    assert helper_flags == cli_flags


def test_launcher_normalizes_paths_and_forwards_all_options(tmp_path):
    module = load_launcher()
    args = module.build_parser().parse_args([
        "--plan", "plan with spaces.json", "-o", "video/out.mp4",
        "--artifacts", "run assets", "--voice", "zh-CN-YunxiNeural",
        "--speed", "1.2", "--planner", "rule", "--bundle", "--subtitles",
    ])
    command = module.build_command(args, tmp_path)
    assert command[:9] == [
        "uv", "run", "--project", str(ROOT), "--locked", "--all-extras",
        "python", "-m", "md2video",
    ]
    for option, value in (
        ("--plan", str(tmp_path / "plan with spaces.json")),
        ("--output", str(tmp_path / "video/out.mp4")),
        ("--artifacts", str(tmp_path / "run assets")),
        ("--voice", "zh-CN-YunxiNeural"), ("--speed", "1.2"),
        ("--planner", "rule"),
    ):
        assert command[command.index(option) + 1] == value
    assert command[-2:] == ["--bundle", "--subtitles"]


def test_launcher_markdown_and_defaults_are_relative_to_caller(tmp_path):
    module = load_launcher()
    args = module.build_parser().parse_args(["script.md"])
    command = module.build_command(args, tmp_path)
    assert command[9] == str(tmp_path / "script.md")
    assert command[command.index("--output") + 1] == str(tmp_path / "output.mp4")
    assert command[command.index("--artifacts") + 1] == str(tmp_path / "artifacts")
    args = module.build_parser().parse_args(["--plan", str(EXAMPLES[0])])
    command = module.build_command(args, tmp_path)
    assert command[command.index("--plan") + 1] == str(EXAMPLES[0])


@pytest.mark.parametrize("arguments", [[], ["script.md", "--plan", "plan.json"]])
def test_launcher_rejects_missing_or_ambiguous_input(arguments):
    with pytest.raises(SystemExit) as exc:
        load_launcher().main(arguments)
    assert exc.value.code == 2


def test_launcher_rejects_missing_file_before_starting_uv(tmp_path, monkeypatch):
    module = load_launcher()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("started uv"))
    with pytest.raises(SystemExit) as exc:
        module.main(["--plan", "missing.json"])
    assert exc.value.code == 2


def test_launcher_reports_missing_uv(tmp_path, monkeypatch, capsys):
    module = load_launcher()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit) as exc:
        module.main(["--plan", "plan.json"])
    assert exc.value.code == 2
    assert "uv not found" in capsys.readouterr().err


def test_launcher_runs_in_repo_and_propagates_exit_status(tmp_path, monkeypatch):
    module = load_launcher()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _: "uv-executable")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main(["--plan", "plan.json", "-o", "nested/output.mp4"]) == 17
    assert (tmp_path / "nested").is_dir()
    assert calls[0][1] == {"cwd": ROOT}
    assert calls[0][0][0] == "uv-executable"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.parent.name)
def test_style_examples_follow_shared_contract_and_schedule(path):
    plan = read_plan(path)
    segments = {segment.id: segment for segment in plan.segments}
    assert len(segments) == len(plan.segments)
    referenced = [sid for scene in plan.scenes for shot in scene.shots for sid in shot.segment_ids]
    assert referenced == [segment.id for segment in plan.segments]
    assert Counter(referenced) == Counter(segments.keys())
    shot_ids = [shot.id for scene in plan.scenes for shot in scene.shots]
    assert len(shot_ids) == len(set(shot_ids))
    visits = defaultdict(list)
    for scene in plan.scenes:
        visits[scene.id].append(scene)
        assert scene.render_backend == "remotion"
        if scene.component:
            assert get_component(scene.component) and is_installed(scene.component)
            assert not any(segments[sid].segment_type.startswith("title_") for sid in scene.all_segment_ids)
    for same_id in visits.values():
        expected = same_id[0]
        for scene in same_id:
            assert (scene.component, scene.visual_type, scene.visual_params) == (
                expected.component, expected.visual_type, expected.visual_params,
            )
        if expected.component.startswith("math_canvas@"):
            ids = {shot.id for scene in same_id for shot in scene.shots}
            assert all(layer["shot"] in ids and layer["kind"] in ("sine", "cosine") for layer in expected.visual_params["layers"])
    assets = ExecutionAssets()
    for segment in plan.segments:
        assert not segment.audio_request if segment.segment_type.startswith("title_") else segment.audio_request
        if segment.audio_request:
            assets.audio_assets.append(AudioAsset(segment_id=segment.id, path="unused.wav", duration=2.0))
    schedule, warnings = build_remotion_schedule(plan, assets, ink_night())
    assert not warnings
    check = check_timeline(plan, assets, schedule["timeline"])
    assert check.ok, check.errors
    assert not check.warnings


@pytest.mark.skipif(
    os.environ.get("MD2VIDEO_RENDER_SMOKE") != "1",
    reason="set MD2VIDEO_RENDER_SMOKE=1 for offline skill example renders",
)
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.parent.name)
def test_style_plan_end_to_end_from_other_directory(path, tmp_path):
    """Real uv/Remotion/FFmpeg, with local test audio cached instead of online TTS.

    This verifies execution, audio facts and subtitles, not online speech quality.
    The example itself keeps all narration requests and is never modified.
    """
    caller = tmp_path / "caller with spaces"
    caller.mkdir()
    plan_path = caller / "plan.json"
    shutil.copyfile(path, plan_path)
    plan = read_plan(plan_path)
    cache_dir = caller / "artifacts/tts"
    cache_dir.mkdir(parents=True)
    cache = ToolCache(cache_dir)
    narrated = [segment for segment in plan.segments if segment.audio_request]
    for segment in narrated:
        request = segment.audio_request
        key = cache.make_key("tts", {"text": segment.text, "voice": request.voice, "speed": request.speed})
        with wave.open(str(cache_dir / f"{key}.{request.format}"), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 32000)
    env = os.environ.copy()
    env["MD2VIDEO_STYLE_PACK"] = "ink_night"
    for key in ("MD2VIDEO_STYLE_PACK_FILE", "MD2VIDEO_COMPONENTS", "MD2VIDEO_LAYOUT_CONSTRAINTS"):
        env.pop(key, None)
    proc = subprocess.run(
        [sys.executable, "-S", str(LAUNCHER), "--plan", "plan.json", "-o", "video/output.mp4",
         "--artifacts", "artifacts", "--planner", "rule", "--subtitles"],
        cwd=caller, env=env, capture_output=True, text=True, timeout=360,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (caller / "video/output.mp4").is_file()
    runs = list((caller / "artifacts/runs").iterdir())
    assert len(runs) == 1
    result = json.loads((runs[0] / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["artifact_index"]["render_provider"] == "remotion"
    assert len(result["used_assets"]["audio"]) == len(narrated) > 0
    assert not result["warnings"], result["warnings"]
    assert (runs[0] / "manifest_viewer.html").is_file()
    assert "Subtitles:" in proc.stdout
