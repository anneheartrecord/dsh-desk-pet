#!/usr/bin/env /usr/bin/python3
"""Inspect the built frames as pixels, not as filenames.

The rest of the suite can only assert that a file exists and differs from
another file. That passed happily while the jellyfish shipped with its eyes
keyed out and sixty holes punched through its body, because a ruined GIF is
still a GIF of the right name and size.

Three things are measured per frame:

* **interior holes** — fully transparent pixels that are *not* reachable from
  the frame border. Those are not background; they are places the key ate the
  character. A flood fill from the edge separates the two.
* **gif vs png coverage** — the desktop pet gets a 1-bit matte and the browser
  gets real alpha, from one source frame. If the two silhouettes disagree by
  much, the threshold is eating the art on the desktop only, where nobody is
  looking at it next to the original.
* **coverage drift within a state** — successive frames of one loop should be
  the same character an instant apart. A big swing means the body is boiling
  between frames.

Plus one cross-skin check: subject bounding boxes and baselines, since a skin
switch that moves the pet 11px vertically reads as a glitch.

    ./scripts/check_frames.py             # human readable, non-zero on failure
    ./scripts/check_frames.py --json      # machine readable, for the tests
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN_ROOT = ROOT / "assets" / "skins"
WEB_ROOT = ROOT / "assets" / "web"

OPAQUE = 128
# Anything smaller is a legitimate enclosed gap (a gap between tentacles, the
# hole in a ring). Bigger than this and the key has taken out real artwork.
MAX_INTERIOR_HOLE_PX = 120
MAX_TOTAL_INTERIOR_PX = 400
# The two matte paths should agree closely; 1-bit quantisation costs a little.
MAX_COVERAGE_DELTA = 0.06
# Frames of one loop are the same body a moment apart.
MAX_INTRA_STATE_DRIFT = 0.10
# Skins should sit on roughly the same baseline so switching does not jump.
MAX_BASELINE_SPREAD_PX = 14


def _rgba(path: Path) -> tuple[bytes, int, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, check=True,
    )
    w, h = (int(v) for v in probe.stdout.decode().strip().split("x"))
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True,
    )
    return out.stdout, w, h


def _alpha_mask(raw: bytes, w: int, h: int) -> bytearray:
    """1 where the subject is, 0 where it is see-through."""

    mask = bytearray(w * h)
    alphas = raw[3::4]
    for i in range(w * h):
        if alphas[i] >= OPAQUE:
            mask[i] = 1
    return mask


def interior_holes(mask: bytearray, w: int, h: int) -> tuple[int, int, int]:
    """(hole count, largest hole px, total hole px) for transparency the border cannot reach."""

    outside = bytearray(w * h)
    queue: deque[int] = deque()
    for x in range(w):
        for i in (x, (h - 1) * w + x):
            if not mask[i] and not outside[i]:
                outside[i] = 1
                queue.append(i)
    for y in range(h):
        for i in (y * w, y * w + w - 1):
            if not mask[i] and not outside[i]:
                outside[i] = 1
                queue.append(i)
    while queue:
        i = queue.popleft()
        x, y = i % w, i // w
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if not mask[j] and not outside[j]:
                    outside[j] = 1
                    queue.append(j)

    seen = bytearray(w * h)
    count = largest = total = 0
    for start in range(w * h):
        if mask[start] or outside[start] or seen[start]:
            continue
        size = 0
        seen[start] = 1
        stack = [start]
        while stack:
            i = stack.pop()
            size += 1
            x, y = i % w, i // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if not mask[j] and not outside[j] and not seen[j]:
                        seen[j] = 1
                        stack.append(j)
        count += 1
        total += size
        largest = max(largest, size)
    return count, largest, total


def bbox(mask: bytearray, w: int, h: int) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = mask[y * w : (y + 1) * w]
        if 1 not in row:
            continue
        first = row.index(1)
        last = w - 1 - row[::-1].index(1)
        x0, x1 = min(x0, first), max(x1, last)
        y0, y1 = min(y0, y), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1)


def inspect(path: Path) -> dict:
    raw, w, h = _rgba(path)
    mask = _alpha_mask(raw, w, h)
    coverage = sum(mask) / (w * h)
    count, largest, total = interior_holes(mask, w, h)
    return {
        "path": str(path.relative_to(ROOT)),
        "size": [w, h],
        "coverage": round(coverage, 4),
        "holes": count,
        "largest_hole": largest,
        "hole_px": total,
        "bbox": bbox(mask, w, h),
    }


def collect() -> dict:
    report: dict = {"frames": {}, "failures": []}
    baselines: dict[str, list[int]] = {}

    for gif in sorted(SKIN_ROOT.glob("*/*/*.gif")):
        skin, state = gif.parts[-3], gif.parts[-2]
        png = WEB_ROOT / skin / state / f"{gif.stem}.png"
        entry = inspect(gif)
        entry["state"] = state
        entry["skin"] = skin
        if png.is_file():
            web = inspect(png)
            entry["web_coverage"] = web["coverage"]
            entry["coverage_delta"] = round(abs(web["coverage"] - entry["coverage"]), 4)
        report["frames"][f"{skin}/{state}/{gif.stem}"] = entry

        if entry["largest_hole"] > MAX_INTERIOR_HOLE_PX:
            report["failures"].append(
                f"{skin}/{state}/{gif.stem}: {entry['largest_hole']}px hole punched through the art"
            )
        if entry["hole_px"] > MAX_TOTAL_INTERIOR_PX:
            report["failures"].append(
                f"{skin}/{state}/{gif.stem}: {entry['hole_px']}px of interior transparency"
            )
        if entry.get("coverage_delta", 0) > MAX_COVERAGE_DELTA:
            report["failures"].append(
                f"{skin}/{state}/{gif.stem}: gif and png silhouettes differ by "
                f"{entry['coverage_delta']:.0%}"
            )
        if entry["bbox"]:
            baselines.setdefault(skin, []).append(entry["bbox"][3])

    for skin, state in {(e["skin"], e["state"]) for e in report["frames"].values()}:
        covers = [
            e["coverage"] for e in report["frames"].values()
            if e["skin"] == skin and e["state"] == state
        ]
        if len(covers) > 1 and max(covers) - min(covers) > MAX_INTRA_STATE_DRIFT:
            report["failures"].append(
                f"{skin}/{state}: body area swings {min(covers):.0%}->{max(covers):.0%} across the loop"
            )

    if baselines:
        per_skin = {skin: sum(v) / len(v) for skin, v in baselines.items()}
        spread = max(per_skin.values()) - min(per_skin.values())
        report["baselines"] = {k: round(v, 1) for k, v in per_skin.items()}
        report["baseline_spread"] = round(spread, 1)
        if spread > MAX_BASELINE_SPREAD_PX:
            report["failures"].append(
                f"skins sit on baselines {spread:.0f}px apart; switching skin makes the pet jump"
            )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["failures"] else 0

    for key, entry in sorted(report["frames"].items()):
        delta = entry.get("coverage_delta")
        note = f" gifVsPng={delta:.1%}" if delta is not None else ""
        print(
            f"  {key:30s} cover={entry['coverage']:.1%} holes={entry['holes']:2d} "
            f"largest={entry['largest_hole']:4d}{note}"
        )
    if report.get("baselines"):
        print(f"\n  baselines: {report['baselines']}  spread={report['baseline_spread']}px")
    if report["failures"]:
        print(f"\n{len(report['failures'])} problem(s):")
        for line in report["failures"]:
            print(f"  ! {line}")
        return 1
    print("\nall frames clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
