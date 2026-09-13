from __future__ import annotations

import argparse
import sys

from md2video.core.pipeline import Pipeline


def main():
    p = argparse.ArgumentParser(description="Markdown to Video - Manifest driven pipeline")
    p.add_argument("input", nargs="?", help="Path to markdown file")
    p.add_argument("--plan", default=None, help="Path to PlanManifest JSON")
    p.add_argument("-o", "--output", default="output.mp4", help="Output video path")
    p.add_argument("--voice", default=None, help="TTS voice (default: zh-CN-YunxiNeural)")
    p.add_argument("--speed", type=float, default=None, help="TTS speed (default: 1.0)")
    p.add_argument("--artifacts", default=None, help="Artifacts directory (default: artifacts/)")
    p.add_argument("--planner", choices=["rule", "llm"], default=None, help="Planner type (default: rule)")
    p.add_argument(
        "--bundle", action="store_true",
        help="Also export an edit-ready media bundle (clips/SRT/EDL/assets) into the run dir",
    )
    p.add_argument(
        "--subtitles", action="store_true",
        help="Burn narration subtitles (content/appendix with audio) into the video",
    )
    args = p.parse_args()

    kwargs = {}
    if args.voice:
        kwargs["voice"] = args.voice
    if args.speed is not None:
        kwargs["speed"] = args.speed
    if args.artifacts:
        kwargs["artifacts_dir"] = args.artifacts
    if args.planner:
        kwargs["planner"] = args.planner
    if args.bundle:
        kwargs["export_bundle"] = True
    if args.subtitles:
        kwargs["burn_subtitles"] = True

    if bool(args.input) == bool(args.plan):
        p.error("provide exactly one input: markdown path or --plan plan.json")

    pipeline = Pipeline(**kwargs)
    try:
        if args.plan:
            output = pipeline.run_plan(args.plan, args.output)
        else:
            output = pipeline.run(args.input, args.output)
        print(f"\nDone! Output: {output}")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
