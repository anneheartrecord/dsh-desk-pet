#!/usr/bin/env /usr/bin/python3
"""Turn chroma-key stills in assets/source into shipped, transparent frames.

Two outputs per source frame, because the two players cannot read the same file:

* ``assets/skins/<skin>/<state>/NN.gif`` — palette GIF with a transparent index.
  macOS ships Tk 8.5, whose ``PhotoImage`` reads GIF and nothing else.
* ``assets/web/<skin>/<state>/NN.png`` — straight RGBA for the in-page overlay.

Cropping is decided once per skin, not per frame: a union bbox keeps every state
on the same baseline so switching state does not make the pet jump or resize.

Needs ffmpeg on PATH. Run after adding art:

    ./scripts/build_frames.py            # everything
    ./scripts/build_frames.py --skin whale
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsh_desk_pet.anim import auto_timeline  # noqa: E402  (needs the path above)

SOURCE_ROOT = ROOT / "assets" / "source"
SKIN_ROOT = ROOT / "assets" / "skins"
WEB_ROOT = ROOT / "assets" / "web"
MANIFEST = SKIN_ROOT / "manifest.json"

FRAME_SIZE = 200
# chromakey similarity/blend. Swept on the whale, whose blue body sits closest
# to its cyan plate: 0.16 still keeps the body, 0.26 eats the whole frame. 0.12
# leaves margin on both sides. Blend stays low because GIF alpha is 1-bit and a
# soft key edge just quantises into a dirty fringe.
SIMILARITY = 0.12
BLEND = 0.02
ALPHA_CUTOFF = 160

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
    return f"chromakey={key}:{SIMILARITY}:{BLEND},format=rgba"


def alpha_bbox(path: Path, key: str) -> tuple[int, int, int, int] | None:
    """Bounding box of pixels the key did not remove, in source pixels."""

    w, h = _probe_size(path)
    raw = _raw_rgba(path, _key_filter(key))
    if len(raw) < w * h * 4:
        return None
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = raw[y * w * 4 : (y + 1) * w * 4]
        # Scan the alpha channel only.
        alphas = row[3::4]
        first = -1
        last = -1
        for x, a in enumerate(alphas):
            if a >= ALPHA_CUTOFF:
                if first < 0:
                    first = x
                last = x
        if first < 0:
            continue
        x0 = min(x0, first)
        x1 = max(x1, last)
        y0 = min(y0, y)
        y1 = max(y1, y)
    if x1 < 0:
        return None
    return x0, y0, x1, y1


def square_crop(bbox: tuple[int, int, int, int], w: int, h: int, pad_ratio: float = 0.06) -> tuple[int, int, int, int]:
    """Grow the union bbox into a padded square that still fits the source."""

    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    side = max(bw, bh)
    side = int(side * (1 + pad_ratio * 2))
    side = min(side, w, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x = int(round(cx - side / 2))
    y = int(round(cy - side / 2))
    x = max(0, min(x, w - side))
    y = max(0, min(y, h - side))
    return x, y, side, side


def build_frame(src: Path, key: str, crop: tuple[int, int, int, int], gif_out: Path, png_out: Path) -> None:
    x, y, cw, ch = crop
    base = f"{_key_filter(key)},crop={cw}:{ch}:{x}:{y},scale={FRAME_SIZE}:{FRAME_SIZE}:flags=lanczos"
    gif_out.parent.mkdir(parents=True, exist_ok=True)
    png_out.parent.mkdir(parents=True, exist_ok=True)

    _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", base,
          "-frames:v", "1", str(png_out)])
    # reserve_transparent keeps one palette slot for the cut-out; alpha_threshold
    # turns the soft key edge into a clean 1-bit matte instead of a grey halo.
    gif_vf = (
        f"{base},split[a][b];"
        f"[a]palettegen=reserve_transparent=1:stats_mode=single[p];"
        f"[b][p]paletteuse=alpha_threshold={ALPHA_CUTOFF}:dither=none"
    )
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", gif_vf,
          "-frames:v", "1", str(gif_out)])


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

    key = chroma_key_hex(frames[0][1])
    w, h = _probe_size(frames[0][1])

    union: tuple[int, int, int, int] | None = None
    for _state, src in frames:
        box = alpha_bbox(src, key)
        if box is None:
            print(f"  ! {src.relative_to(ROOT)} keyed to nothing, skipping bbox")
            continue
        union = box if union is None else (
            min(union[0], box[0]), min(union[1], box[1]),
            max(union[2], box[2]), max(union[3], box[3]),
        )
    if union is None:
        raise SystemExit(f"skin {skin}: every frame keyed to nothing (wrong key {key}?)")
    crop = square_crop(union, w, h)

    built: dict[str, list[str]] = {}
    for state, src in frames:
        gif = SKIN_ROOT / skin / state / f"{src.stem}.gif"
        png = WEB_ROOT / skin / state / f"{src.stem}.png"
        build_frame(src, key, crop, gif, png)
        built.setdefault(state, []).append(gif.name)
        print(f"  {skin}/{state}/{src.stem}  key={key} crop={crop}")

    states = {k: sorted(v) for k, v in built.items()}
    # Bake the rhythm into the manifest so the browser overlay plays the exact
    # same loop as the desktop window instead of reimplementing the timing.
    timelines = {
        state: [list(step) for step in auto_timeline(state, len(names)).steps]
        for state, names in states.items()
    }
    return {"key": key, "crop": list(crop), "states": states, "timelines": timelines}


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
