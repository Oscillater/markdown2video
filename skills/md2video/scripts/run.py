"""Run the repository CLI from any directory, without global Python packages.

Only path normalization and uv delegation live here. The video pipeline remains
in md2video; this file deliberately imports only the Python standard library.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Markdown path, relative to caller")
    parser.add_argument("--plan", help="Plan JSON path, relative to caller")
    parser.add_argument("-o", "--output", default="output.mp4")
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--voice")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--planner", choices=("rule", "llm"))
    parser.add_argument("--bundle", action="store_true")
    parser.add_argument("--subtitles", action="store_true")
    return parser


def absolute_path(value: str, caller_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = caller_dir / path
    return path.resolve()


def build_command(
    args: argparse.Namespace,
    caller_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    uv: str = "uv",
) -> list[str]:
    command = [
        uv, "run", "--project", str(repo_root), "--locked", "--all-extras",
        "python", "-m", "md2video",
    ]
    if args.plan:
        command.extend(["--plan", str(absolute_path(args.plan, caller_dir))])
    else:
        command.append(str(absolute_path(args.input, caller_dir)))
    command.extend([
        "--output", str(absolute_path(args.output, caller_dir)),
        "--artifacts", str(absolute_path(args.artifacts, caller_dir)),
    ])
    for name in ("voice", "speed", "planner"):
        value = getattr(args, name)
        if value is not None:
            command.extend([f"--{name}", str(value)])
    for name in ("bundle", "subtitles"):
        if getattr(args, name):
            command.append(f"--{name}")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.input) == bool(args.plan):
        parser.error("provide exactly one input: markdown path or --plan plan.json")
    caller_dir = Path.cwd()
    source = absolute_path(args.plan or args.input, caller_dir)
    if not source.is_file():
        parser.error(f"Input file not found: {source}")
    if not (REPO_ROOT / "pyproject.toml").is_file() or not (
        REPO_ROOT / "md2video" / "__main__.py"
    ).is_file():
        parser.error("Keep this launcher inside the complete markdown2video repository")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv not found on PATH; install uv before running this skill")

    try:
        absolute_path(args.output, caller_dir).parent.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            build_command(args, caller_dir, uv=uv), cwd=REPO_ROOT,
        ).returncode
    except OSError as exc:
        print(f"Cannot launch markdown2video: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
