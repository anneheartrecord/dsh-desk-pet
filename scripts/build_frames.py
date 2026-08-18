#!/usr/bin/env /usr/bin/python3
"""Turn chroma-key stills in assets/source into shipped, transparent frames.

Two outputs per source frame, of which only one is still played:

* ``assets/web/<skin>/<state>/NN.png`` — straight RGBA. **This is the tree the
  pet renders from**, whatever its name suggests: every call into `packs` passes
  ``web=True``. The name is left over from an in-page pet that no longer exists,
  and it is a trap worth stating outright — deleting "the web assets" deletes all
  the art.
* ``assets/skins/<skin>/<state>/NN.gif`` — palette GIF with a transparent index,
  for Tk's ``PhotoImage``, which reads GIF and nothing else. Nothing loads these
  now that the renderer is AppKit; they are still built so the format is one
  command away, but they are excluded from the published package.

Cropping is decided once per skin, not per frame: a union bbox keeps every state
on the same baseline so switching state does not make the pet jump or resize.

The geometry, the keying constants and the PNG writer live in
``src/dsh_desk_pet/imaging.py`` now, and this script imports them. ``scripts/``
is not published, so a copy kept here would be out of reach of the installed
package — which needs exactly those operations to install a user's own skin —
and two copies of the coverage contract would drift from the gate that enforces
it.

Needs ffmpeg on PATH. Run after adding art:

    ./scripts/build_frames.py            # everything
    ./scripts/build_frames.py --skin whale
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
import zlib
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsh_desk_pet.anim import auto_timeline  # noqa: E402  (needs the path above)
from dsh_desk_pet.imaging import (  # noqa: E402
    ALPHA_CUTOFF,
    BASELINE_RATIO,
    FRAME_SIZE,
    PLATE_DISTANCE,
    SIMILARITY,
    SOURCE_PAD_RATIO,
    TARGET_COVERAGE,
    _despill_edges,
    _hex_rgb,
    _seal_interior,
    _write_png_rgba,
    square_crop,
)

SOURCE_ROOT = ROOT / "assets" / "source"
SKIN_ROOT = ROOT / "assets" / "skins"
WEB_ROOT = ROOT / "assets" / "web"
MANIFEST = SKIN_ROOT / "manifest.json"

# `colorkey`, not `chromakey`: chromakey matches on chroma alone and ignores
# luma, so against a pastel plate it deletes the character's black eyes.
#
# The stills are all generated on magenta, which appears nowhere in any of these
# palettes. That is what makes the tolerance below generous rather than a
# compromise: measured across all four skins, subject coverage is identical at
# 0.08 and at 0.32, so nothing of the character is at stake anywhere in that
# range. It only starts costing art at 0.40. 0.24 comfortably absorbs the
# plate-to-plate variation between generations (0xF208EC..0xF805EB) with room
# to spare on both sides.
#
# Blend stays at 0: GIF alpha is 1-bit, so a soft key edge only quantises into
# a fringe. `_despill_edges` cleans the edge afterwards instead.
BLEND = 0.0
# Where the bottom of the body sits inside the square crop. Shared by every
# skin so switching skin does not move the pet vertically.
# How much of the finished frame the character should cover. Every skin is
# scaled to hit this, so switching skin does not change the pet's apparent size.
# How much plate `build_frame` adds around a source before cropping. The crop
# may use it, so `square_crop` must know the same number.
# Sum-of-channel distance under which an enclosed region counts as the plate
# showing through rather than artwork the key removed.



STATES = ("idle", "working", "waiting", "error", "happy", "sleeping")


def _run(cmd: list[str], *, capture: bool = False) -> bytes:
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.decode('utf-8', 'replace')[-400:]}")
    return proc.stdout if capture else b""


def _probe_size(path: Path) -> tuple[int, int]:
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path),
        ],
        capture=True,
    )
    w, h = out.decode().strip().split("x")
    return int(w), int(h)


def _raw_rgba(path: Path, vf: str) -> bytes:
    return _run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf,
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture=True,
    )


def chroma_key_hex(path: Path) -> str:
    """Sample the four corners; the generator paints a flat plate behind the art."""

    w, h = _probe_size(path)
    patch = max(2, min(w, h) // 40)
    samples: list[tuple[int, int, int]] = []
    for x, y in ((0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)):
        raw = _raw_rgba(path, f"crop={patch}:{patch}:{x}:{y},scale=1:1")
        samples.append((raw[0], raw[1], raw[2]))
    # Median per channel: a corner clipped by the art cannot drag the key.
    r, g, b = (sorted(c[i] for c in samples)[len(samples) // 2] for i in range(3))
    return f"0x{r:02X}{g:02X}{b:02X}"


def _key_filter(key: str) -> str:
    return f"colorkey={key}:{SIMILARITY}:{BLEND},format=rgba"


def alpha_bbox(path: Path, key: str) -> tuple[tuple[float, float, float, float] | None, float]:
    """Body bounding box (relative 0..1) and subject coverage for one keyed frame.

    Relative, not pixels, because the source stills do not share a resolution:
    the original art is 360x360 and everything generated since comes back at
    1024x1024. Unioning raw pixel boxes across those silently produced a crop
    the size of the whole frame.

    Rows and columns holding only a handful of opaque pixels are ignored. The
    celebration and sleeping poses scatter sparkles and ZZZ near the frame edge,
    and letting those set the crop would zoom every other frame of the skin out
    to match, shrinking the character for no reason.
    """

    w, h = _probe_size(path)
    raw = _raw_rgba(path, _key_filter(key))
    if len(raw) < w * h * 4:
        return None, 0.0

    alphas = raw[3::4]
    row_counts = [0] * h
    col_counts = [0] * w
    opaque = 0
    for y in range(h):
        base = y * w
        for x in range(w):
            if alphas[base + x] >= ALPHA_CUTOFF:
                row_counts[y] += 1
                col_counts[x] += 1
                opaque += 1

    coverage = opaque / float(w * h)
    row_floor = max(2, int(w * 0.012))
    col_floor = max(2, int(h * 0.012))
    rows = [y for y, c in enumerate(row_counts) if c >= row_floor]
    cols = [x for x, c in enumerate(col_counts) if c >= col_floor]
    if not rows or not cols:
        return None, coverage
    return (cols[0] / w, rows[0] / h, (cols[-1] + 1) / w, (rows[-1] + 1) / h), coverage










def build_frame(src: Path, key: str, crop: tuple[int, int, int, int], gif_out: Path, png_out: Path) -> int:
    x, y, cw, ch = crop
    w, h = _probe_size(src)
    # Grow the canvas with more plate before cropping, so a crop box that runs
    # off the edge simply lands on background instead of having to be clamped
    # back inside — clamping moves the character within the frame, which is the
    # one thing the baseline anchoring exists to prevent.
    pad = int(round(SOURCE_PAD_RATIO * min(w, h)))
    base = (
        f"pad={w + 2 * pad}:{h + 2 * pad}:{pad}:{pad}:color={key.replace('0x', '#')},"
        f"{_key_filter(key)},"
        f"crop={cw}:{ch}:{x + pad}:{y + pad},"
        f"scale={FRAME_SIZE}:{FRAME_SIZE}:flags=lanczos"
    )
    gif_out.parent.mkdir(parents=True, exist_ok=True)
    png_out.parent.mkdir(parents=True, exist_ok=True)

    raw = bytearray(_raw_rgba(src, base))
    expected = FRAME_SIZE * FRAME_SIZE * 4
    if len(raw) < expected:
        raise RuntimeError(f"{src}: expected {expected} bytes of RGBA, got {len(raw)}")
    sealed = _seal_interior(raw, FRAME_SIZE, FRAME_SIZE, key)
    _despill_edges(raw, FRAME_SIZE, FRAME_SIZE)
    _write_png_rgba(png_out, FRAME_SIZE, FRAME_SIZE, bytes(raw[:expected]))

    # The GIF is derived from the sealed PNG, not re-keyed from the source, so
    # the two matte paths cannot disagree. reserve_transparent keeps a palette
    # slot for the cut-out; alpha_threshold makes a clean 1-bit edge instead of
    # a grey halo.
    gif_vf = (
        "split[a][b];"
        "[a]palettegen=reserve_transparent=1:stats_mode=single[p];"
        f"[b][p]paletteuse=alpha_threshold={ALPHA_CUTOFF}:dither=none"
    )
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(png_out), "-filter_complex", gif_vf,
          "-frames:v", "1", str(gif_out)])
    return sealed


def build_skin(skin: str) -> dict:
    skin_src = SOURCE_ROOT / skin
    frames: list[tuple[str, Path]] = []
    for state in STATES:
        state_dir = skin_src / state
        if not state_dir.is_dir():
            continue
        for src in sorted(state_dir.glob("*.png")):
            frames.append((state, src))
    if not frames:
        raise SystemExit(f"no source frames for skin {skin}")

    # Each still is a separate generation, so its plate is only *nearly* the
    # same colour as the reference's. Sampling one key and reusing it leaves a
    # frame unkeyed, which then drags the union bbox out to the whole image and
    # silently un-crops every other frame in the skin.
    keys = {src: chroma_key_hex(src) for _state, src in frames}

    union: tuple[float, float, float, float] | None = None
    boxes: dict[Path, tuple[float, float, float, float]] = {}
    # Fraction of the source each pose actually inks. The median across a
    # skin's poses is what sets its scale — the mean would let one sprawling
    # celebration pose shrink every other frame.
    coverages: list[float] = []
    for _state, src in frames:
        box, coverage = alpha_bbox(src, keys[src])
        if box is None:
            print(f"  ! {src.relative_to(ROOT)} keyed to nothing, ignoring for crop")
            continue
        # Coverage, not bbox area: the celebration pose legitimately spans most
        # of the frame, so area cannot tell "wide pose" from "key did nothing".
        if coverage > 0.85:
            print(f"  ! {src.relative_to(ROOT)} key {keys[src]} left {coverage:.0%} opaque, ignoring for crop")
            continue
        boxes[src] = box
        coverages.append(coverage)
        union = box if union is None else (
            min(union[0], box[0]), min(union[1], box[1]),
            max(union[2], box[2]), max(union[3], box[3]),
        )
    if union is None:
        raise SystemExit(f"skin {skin}: no frame keyed cleanly; check the plates in assets/source/{skin}")

    built: dict[str, list[str]] = {}
    for state, src in frames:
        gif = SKIN_ROOT / skin / state / f"{src.stem}.gif"
        png = WEB_ROOT / skin / state / f"{src.stem}.png"
        # Sized from the skin, positioned from this pose, in this frame's own
        # resolution — the sources arrive at 360, 1024 and 1254px.
        src_w, src_h = _probe_size(src)
        median = sorted(coverages)[len(coverages) // 2] if coverages else 0.0
        crop = square_crop(
            union, src_w, src_h,
            frame=boxes.get(src),
            area_px=median * src_w * src_h,
        )
        sealed = build_frame(src, keys[src], crop, gif, png)
        built.setdefault(state, []).append(gif.name)
        note = f" sealed={sealed}px" if sealed else ""
        print(f"  {skin}/{state}/{src.stem}  key={keys[src]} crop={crop}{note}")

    states = {state: sorted(names) for state, names in built.items()}

    # Where the character actually sits inside the finished frame. The window
    # is sized from this rather than from the frame, because the frame is
    # square with padding and the window is a rectangle that swallows every
    # click landing on it — padding is dead screen.
    subject = _subject_box(SKIN_ROOT / skin)
    # Bake the rhythm into the manifest rather than leaving it in code, so the
    # timing travels with the art and a rebuilt skin cannot drift out of step.
    timelines = {
        state: [list(step) for step in auto_timeline(state, len(names)).steps]
        for state, names in states.items()
    }
    # `crop` is relative because the source stills come back at three different
    # resolutions; each frame resolves it against its own size at build time.
    return {
        "keys": {f"{src.parent.name}/{src.stem}": keys[src] for _state, src in frames},
        "crop_relative": [round(v, 4) for v in union],
        "subject_box": subject,
        "states": states,
        "timelines": timelines,
    }


def _subject_box(skin_dir: Path) -> list[int]:
    """Union bbox of the drawn character across every built frame of a skin.

    In final-frame pixels, so the runtime can size its window to the animal
    rather than to the padded square it is drawn on.
    """

    x0, y0, x1, y1 = FRAME_SIZE, FRAME_SIZE, 0, 0
    for gif in sorted(skin_dir.glob("*/*.gif")):
        raw = _raw_rgba(gif, "null")
        if len(raw) < FRAME_SIZE * FRAME_SIZE * 4:
            continue
        alphas = raw[3::4]
        for y in range(FRAME_SIZE):
            base = y * FRAME_SIZE
            row = [x for x in range(FRAME_SIZE) if alphas[base + x] >= ALPHA_CUTOFF]
            if not row:
                continue
            x0, x1 = min(x0, row[0]), max(x1, row[-1])
            y0, y1 = min(y0, y), max(y1, y)
    if x1 <= x0:
        return [0, 0, FRAME_SIZE - 1, FRAME_SIZE - 1]
    return [x0, y0, x1, y1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skin", action="append", help="limit to these skins")
    args = parser.parse_args()

    skins = args.skin or sorted(p.name for p in SOURCE_ROOT.iterdir() if p.is_dir())
    manifest = {}
    if MANIFEST.is_file():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest.setdefault("frame_size", FRAME_SIZE)
    manifest.setdefault("skins", {})

    for skin in skins:
        print(f"building {skin}")
        manifest["skins"][skin] = build_skin(skin)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
