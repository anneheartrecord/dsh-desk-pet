#!/usr/bin/env /usr/bin/python3
"""Tile every shipped frame into one reviewable image.

The pet only exists on screen, and this repo's tests run headless, so a
reviewer needs some way to see what changed without a window server. This
composites `assets/web/**` onto a loud magenta plate — anything the chroma key
missed shows up as a grey fringe against it, and any hole in the subject shows
up as magenta bleeding through the pet.

    ./scripts/contact_sheet.py                 # -> build/contact-sheet.png
    ./scripts/contact_sheet.py --bg 0x101014   # dark plate instead
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "assets" / "web"
DEFAULT_OUT = ROOT / "build" / "contact-sheet.png"

STATE_ORDER = ("idle", "working", "waiting", "error", "happy", "sleeping")
CELL = 160


def collect() -> tuple[list[str], list[list[Path]]]:
    skins = sorted(p.name for p in WEB_ROOT.iterdir() if p.is_dir())
    grid: list[list[Path]] = []
    for skin in skins:
        row: list[Path] = []
        for state in STATE_ORDER:
            row.extend(sorted((WEB_ROOT / skin / state).glob("*.png")))
        grid.append(row)
    return skins, grid


def build(out: Path, bg: str) -> None:
    skins, grid = collect()
    if not grid:
        raise SystemExit("no frames under assets/web — run scripts/build_frames.py first")
    cols = max(len(row) for row in grid)
    rows = len(grid)
    width, height = cols * CELL, rows * CELL

    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={width}x{height}"]
    flat: list[tuple[int, int]] = []
    for r, row in enumerate(grid):
        for c, path in enumerate(row):
            cmd += ["-i", str(path)]
            flat.append((r, c))

    steps = []
    prev = "[0]"
    for i, (r, c) in enumerate(flat, start=1):
        label = f"[v{i}]"
        scaled = f"[s{i}]"
        steps.append(f"[{i}]scale={CELL}:{CELL}{scaled}")
        steps.append(f"{prev}{scaled}overlay={c * CELL}:{r * CELL}{label}")
        prev = label
    # Drop the trailing label so ffmpeg maps the final link to the output.
    filter_complex = ";".join(steps)
    filter_complex = filter_complex.rsplit(prev, 1)[0].rstrip(";")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd += ["-filter_complex", filter_complex, "-frames:v", "1", str(out)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", "replace")[-800:])
    print(f"wrote {out.relative_to(ROOT)}  {cols} cols x {rows} rows  skins={', '.join(skins)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bg", default="0xFF00FF", help="plate colour behind the cut-outs")
    args = parser.parse_args()
    build(args.out, args.bg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
