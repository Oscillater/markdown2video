from __future__ import annotations

import argparse
import sys

from md2video.core.pipeline import Pipeline


def main():
    p = argparse.ArgumentParser(description="Markdown to Video - Manifest driven pipeline")
    p.add_argument("input", help="Path to markdown file")
    p.add_argument("-o", "--output", default="output.mp4", help="Output video path")
    p.add_argument("--voice", default=None, help="TTS voice (default: zh-CN-YunxiNeural)")
    p.add_argument("--speed", type=float, default=None, help="TTS speed (default: 1.0)")
    p.add_argument("--artifacts", default=None, help="Artifacts directory (default: artifacts/)")
    args = p.parse_args()

    kwargs = {}
    if args.voice:
        kwargs["voice"] = args.voice
    if args.speed is not None:
        kwargs["speed"] = args.speed
    if args.artifacts:
        kwargs["artifacts_dir"] = args.artifacts

    pipeline = Pipeline(**kwargs)
    try:
        output = pipeline.run(args.input, args.output)
        print(f"\nDone! Output: {output}")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
