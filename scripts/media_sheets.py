#!/usr/bin/env /usr/bin/python3
"""Build the preview images the READMEs show, one set per skin.

Separate from `contact_sheet.py` on purpose. That one tiles *every* frame onto
one plate so a reviewer can spot a bad key without a window server; it is a
diagnostic and it looks like one. These are the images a stranger sees first,
so they show one representative frame per state, evenly spaced, at a size that
survives GitHub's 820px content column.

The animated strip honours the real timeline out of `assets/skins/manifest.json`
rather than giving every frame an equal slice. Idle is 2.4s of stillness and
then a blink measured in tens of milliseconds — flatten that to three equal
frames and the pet reads as a twitching sprite instead of a breathing one,
which is the single thing the still images cannot show.

    ./scripts/media_sheets.py            # -> docs/media/skin-<id>.png and .gif
    ./scripts/media_sheets.py --no-gif   # stills only, no ffmpeg needed
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsh_desk_pet import imaging  # noqa: E402

WEB_ROOT = ROOT / "assets" / "web"
MANIFEST = ROOT / "assets" / "skins" / "manifest.json"
OUT_DIR = ROOT / "docs" / "media"

STATE_ORDER = ("idle", "working", "waiting", "error", "happy", "sleeping")
CELL = 180
GAP = 16
PAD = 20
PLATE = (0x0D, 0x0D, 0x12)


def _blank(width: int, height: int) -> bytearray:
    row = bytes((*PLATE, 255)) * width
    return bytearray(row * height)


def _paste(dst: bytearray, dst_w: int, src: bytes, src_w: int, src_h: int,
           x0: int, y0: int) -> None:
    """Alpha-composite one decoded RGBA image onto the plate."""

    for y in range(src_h):
        drow = (y0 + y) * dst_w
        for x in range(src_w):
            s = (y * src_w + x) * 4
            a = src[s + 3]
            if not a:
                continue
            d = (drow + x0 + x) * 4
            if a == 255:
                dst[d:d + 4] = src[s:s + 4]
            else:
                for c in range(3):
                    dst[d + c] = (src[s + c] * a + dst[d + c] * (255 - a)) // 255


def _frame(skin: str, state: str, index: int = 0) -> tuple[bytes, int, int]:
    path = WEB_ROOT / skin / state / f"{index:02d}.png"
    width, height, pixels = imaging.decode_png(path.read_bytes())
    if (width, height) != (CELL, CELL):
        pixels = imaging.crop_scale(pixels, width, height, (0, 0, width, height), CELL)
        width = height = CELL
    return pixels, width, height


def build_strip(skin: str, out: Path) -> None:
    states = [s for s in STATE_ORDER if (WEB_ROOT / skin / s / "00.png").is_file()]
    width = PAD * 2 + CELL * len(states) + GAP * (len(states) - 1)
    height = PAD * 2 + CELL
    plate = _blank(width, height)
    for i, state in enumerate(states):
        pixels, w, h = _frame(skin, state)
        _paste(plate, width, pixels, w, h, PAD + i * (CELL + GAP), PAD)
    imaging._write_png_rgba(out, width, height, bytes(plate))


def build_loop(skin: str, state: str, out: Path, timelines: dict) -> bool:
    """Animate one state at its shipped cadence. Returns False without ffmpeg."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    steps = timelines.get(state)
    if not steps:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Flatten each frame onto the plate first: GIF carries one bit of
        # alpha, so a soft edge keyed against nothing fringes badly.
        for index in sorted({int(i) for i, _ in steps}):
            pixels, w, h = _frame(skin, state, index)
            plate = _blank(w + PAD * 2, h + PAD * 2)
            _paste(plate, w + PAD * 2, pixels, w, h, PAD, PAD)
            imaging._write_png_rgba(tmp_dir / f"{index:02d}.png", w + PAD * 2,
                                    h + PAD * 2, bytes(plate))

        concat = tmp_dir / "list.txt"
        lines = []
        for index, ms in steps:
            lines.append(f"file '{tmp_dir / f'{int(index):02d}.png'}'")
            lines.append(f"duration {max(int(ms), 20) / 1000:.3f}")
        lines.append(f"file '{tmp_dir / f'{int(steps[-1][0]):02d}.png'}'")
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

        palette = tmp_dir / "palette.png"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat), "-vf", "palettegen=stats_mode=diff",
                        str(palette)], check=True)
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat), "-i", str(palette), "-lavfi",
                        "paletteuse=dither=bayer:bayer_scale=3", "-loop", "0",
                        str(out)], check=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gif", action="store_true", help="skip the animated loops")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")).get("skins", {})
    skins = sorted(p.name for p in WEB_ROOT.iterdir() if p.is_dir())

    for skin in skins:
        strip = args.out / f"skin-{skin}.png"
        build_strip(skin, strip)
        print(f"{strip.relative_to(ROOT)}")
        if args.no_gif:
            continue
        timelines = manifest.get(skin, {}).get("timelines", {})
        loop = args.out / f"loop-{skin}.gif"
        if build_loop(skin, "idle", loop, timelines):
            print(f"{loop.relative_to(ROOT)}")
        else:
            print(f"  (skipped {loop.name}: no ffmpeg or no timeline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
