#!/usr/bin/env /usr/bin/python3
"""Build the preview images the READMEs show, one set per shipped skin.

The still strips come from `dsh_desk_pet.sheets`, which ships — anyone who
installed the plugin can produce the same image for their own skin with
`dsh-desk-pet --skin-sheet <id>`. Only the animated loops live here, because
they need ffmpeg and the runtime deliberately does not.

The loop honours the real timeline out of `assets/skins/manifest.json` rather
than giving every frame an equal slice. Idle is 2.4s of stillness and then a
blink measured in tens of milliseconds — flatten that and the pet reads as a
twitching sprite instead of a breathing one, which is the one thing the stills
cannot show.

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

from dsh_desk_pet import imaging, packs, sheets  # noqa: E402

MANIFEST = ROOT / "assets" / "skins" / "manifest.json"
OUT_DIR = ROOT / "docs" / "media"


def build_loop(skin: str, state: str, out: Path, timelines: dict) -> bool:
    """Animate one state at its shipped cadence. Returns False without ffmpeg."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    steps = timelines.get(state)
    if not steps:
        return False

    pad = sheets.PAD
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Flatten each frame onto the plate first: GIF carries one bit of
        # alpha, so a soft keyed edge fringes badly against anything else.
        for index in sorted({int(i) for i, _ in steps}):
            pixels, w, h = sheets.frame_image(skin, state, index)
            plate = sheets._blank(w + pad * 2, h + pad * 2)
            sheets._composite(plate, w + pad * 2, pixels, w, h, pad, pad)
            imaging._write_png_rgba(tmp_dir / f"{index:02d}.png",
                                    w + pad * 2, h + pad * 2, bytes(plate))

        concat = tmp_dir / "list.txt"
        lines = []
        for index, ms in steps:
            lines.append(f"file '{tmp_dir / f'{int(index):02d}.png'}'")
            lines.append(f"duration {max(int(ms), 20) / 1000:.3f}")
        # The concat demuxer ignores the last duration, so the final frame is
        # repeated to give the preceding step its time.
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

    # Shipped only: this writes into the repo's own docs, and a skin the
    # developer happens to have installed is not part of the release.
    for skin in packs.shipped_skins():
        strip = sheets.build_strip(skin, args.out / f"skin-{skin}.png")
        print(strip.relative_to(ROOT))
        if args.no_gif:
            continue
        loop = args.out / f"loop-{skin}.gif"
        if build_loop(skin, "idle", loop, manifest.get(skin, {}).get("timelines", {})):
            print(loop.relative_to(ROOT))
        else:
            print(f"  (skipped {loop.name}: no ffmpeg or no timeline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
