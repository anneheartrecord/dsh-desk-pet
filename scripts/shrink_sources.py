#!/usr/bin/env /usr/bin/python3
"""Downscale the generated stills to the smallest size the build still needs.

The image API returns 1024–1254px PNGs, and 72 of those is ~89MB — against a
shipped output of under 5MB. That matters because `dsh plugin add
github:owner/repo` fetches the whole repository tree, so every megabyte of build
input is a megabyte of install time for someone who only ever sees the 200px
frames.

512px is chosen with room to spare: `build_frames.py` crops to roughly 94% of
the source and scales that to 200, so 512 still leaves about 2.4x oversampling
for the lanczos pass. Frames already at or below the target are left alone, so
this is safe to re-run.

    ./scripts/shrink_sources.py            # rewrite in place
    ./scripts/shrink_sources.py --dry-run  # just report
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "assets" / "source"
TARGET = 512


def _size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, check=True,
    ).stdout.decode().strip()
    w, h = out.split("x")
    return int(w), int(h)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    before = after = 0
    touched = 0
    for src in sorted(SOURCE_ROOT.glob("*/*/*.png")):
        size = src.stat().st_size
        before += size
        w, h = _size(src)
        if max(w, h) <= args.target:
            after += size
            continue
        touched += 1
        if args.dry_run:
            after += size // ((w // args.target) ** 2 or 1)
            continue
        tmp = src.with_suffix(".resized.png")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-vf", f"scale={args.target}:{args.target}:flags=lanczos", str(tmp)],
            check=True,
        )
        tmp.replace(src)
        after += src.stat().st_size

    verb = "would shrink" if args.dry_run else "shrank"
    print(f"{verb} {touched} of {len(list(SOURCE_ROOT.glob('*/*/*.png')))} stills")
    print(f"  {before / 1e6:.1f}MB -> {after / 1e6:.1f}MB")
    if not args.dry_run and touched:
        print("  rerun ./scripts/build_frames.py to rebuild from the smaller sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
