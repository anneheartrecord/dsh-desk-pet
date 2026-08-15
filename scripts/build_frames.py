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
import struct
import subprocess
import sys
import zlib
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsh_desk_pet.anim import auto_timeline  # noqa: E402  (needs the path above)

SOURCE_ROOT = ROOT / "assets" / "source"
SKIN_ROOT = ROOT / "assets" / "skins"
WEB_ROOT = ROOT / "assets" / "web"
MANIFEST = SKIN_ROOT / "manifest.json"

FRAME_SIZE = 200
# `colorkey`, not `chromakey`. chromakey matches on chroma alone and ignores
# luma, so against a pastel plate like the jellyfish's mint (0xA4F4CC) every
# near-neutral pixel in the art falls inside the radius — it was deleting the
# character's black eyes and punching 60 holes through its body. colorkey
# compares full RGB distance and leaves them alone.
#
# 0.08 measured across all four skins: jellyfish interior holes 1015 -> 180,
# nautilus and whale unchanged at 0, threadcore unchanged. Blend stays at 0
# because GIF alpha is 1-bit and any soft edge just quantises into a fringe.
SIMILARITY = 0.08
BLEND = 0.0
ALPHA_CUTOFF = 160
# Where the bottom of the body sits inside the square crop. Shared by every
# skin so switching skin does not move the pet vertically.
BASELINE_RATIO = 0.94
# Sum-of-channel distance under which an enclosed region counts as the plate
# showing through rather than artwork the key removed.
PLATE_DISTANCE = 150


def _hex_rgb(value: str) -> tuple[int, int, int]:
    # Strip the prefix, not a character set: `lstrip("0x")` eats every leading
    # '0' and 'x', so "0x00E412" becomes "E412" and the parse silently shifts.
    raw = value.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    elif raw[:2].lower() == "0x":
        raw = raw[2:]
    if len(raw) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)

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


def square_crop(
    union: tuple[float, float, float, float],
    w: int,
    h: int,
    frame: tuple[float, float, float, float] | None = None,
    pad_ratio: float = 0.06,
) -> tuple[int, int, int, int]:
    """Square crop for one frame: sized from the skin, positioned from the pose.

    Two different jobs, deliberately fed by two different boxes.

    *Size* comes from the skin's union box, so every frame of a skin is drawn at
    the same scale and the character never grows or shrinks between states.

    *Position* comes from this frame's own box, anchored so the bottom of the
    body lands at `BASELINE_RATIO`. Anchoring on the union instead let each pose
    sit wherever its own extent happened to fall — up to 25px apart within one
    skin, so the pet visibly hopped whenever it changed state. Vertical movement
    is the renderer's job (breath, hop); the art should hold still.
    """

    ux0, uy0, ux1, uy1 = union[0] * w, union[1] * h, union[2] * w, union[3] * h
    side = max(ux1 - ux0, uy1 - uy0) * (1 + pad_ratio * 2)
    side = int(round(min(side, w, h)))

    box = frame or union
    fx0, fy1 = box[0] * w, box[3] * h
    fx1 = box[2] * w
    cx = (fx0 + fx1) / 2
    x = max(0, min(int(round(cx - side / 2)), w - side))
    y = max(0, min(int(round(fy1 - side * BASELINE_RATIO)), h - side))
    return x, y, side, side


def _seal_interior(raw: bytearray, w: int, h: int, key: str) -> int:
    """Restore transparency the key opened up *inside* the character.

    Being unreachable from the border is necessary but not sufficient. A ball of
    yarn with thirty loose strands encloses thirty loops of real background, and
    sealing those is how `threadcore/error` came to ship sitting on a bright
    green flower.

    Colour settles it. `colorkey` only zeroes alpha and leaves RGB untouched, so
    a region cut out of the artwork still holds the artwork's colours, while
    genuine background still holds the plate's. Regions that look like the plate
    stay transparent; regions that look like the character are restored — and
    because their RGB survived the key, restoring alpha is all it takes to bring
    them back correctly coloured.

    Returns how many pixels were restored.
    """

    key_rgb = _hex_rgb(key)
    reachable = bytearray(w * h)
    queue: deque[int] = deque()

    def push(i: int) -> None:
        if not reachable[i] and raw[i * 4 + 3] < ALPHA_CUTOFF:
            reachable[i] = 1
            queue.append(i)

    for x in range(w):
        push(x)
        push((h - 1) * w + x)
    for y in range(h):
        push(y * w)
        push(y * w + w - 1)

    while queue:
        i = queue.popleft()
        x, y = i % w, i // w
        if x > 0:
            push(i - 1)
        if x < w - 1:
            push(i + 1)
        if y > 0:
            push(i - w)
        if y < h - 1:
            push(i + w)

    sealed = 0
    seen = bytearray(w * h)
    for start in range(w * h):
        if reachable[start] or seen[start] or raw[start * 4 + 3] >= ALPHA_CUTOFF:
            continue
        # Collect one enclosed region, then judge it as a whole: a per-pixel
        # test would leave a speckled halo of the few pixels that fell either
        # side of the threshold.
        region = []
        seen[start] = 1
        stack = [start]
        total = [0, 0, 0]
        while stack:
            i = stack.pop()
            region.append(i)
            total[0] += raw[i * 4]
            total[1] += raw[i * 4 + 1]
            total[2] += raw[i * 4 + 2]
            x, y = i % w, i // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if not seen[j] and not reachable[j] and raw[j * 4 + 3] < ALPHA_CUTOFF:
                        seen[j] = 1
                        stack.append(j)

        n = len(region)
        mean = (total[0] / n, total[1] / n, total[2] / n)
        if sum(abs(mean[c] - key_rgb[c]) for c in range(3)) < PLATE_DISTANCE:
            continue  # genuinely background, just walled in by the artwork
        for i in region:
            raw[i * 4 + 3] = 255
        sealed += n
    return sealed


def _despill_edges(raw: bytearray, w: int, h: int) -> int:
    """Repaint the contaminated ring of pixels along the silhouette.

    A keyed edge pixel is a blend of the character and the plate behind it, so
    it keeps a tint of the plate: measured across these skins, over half of all
    edge pixels sat closer to the key colour than to the art. On a light
    background that is invisible, which is why it survived this long; on a dark
    desktop it is a green or cyan halo tracing the outline.

    Rather than model the spill, each edge pixel takes the average colour of
    its *interior* neighbours — pixels that are opaque and not themselves on
    the edge, so uncontaminated by construction. Alpha is untouched, so the
    silhouette does not change shape.
    """

    edge = bytearray(w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if raw[i * 4 + 3] < ALPHA_CUTOFF:
                continue
            if (
                raw[(i - 1) * 4 + 3] < ALPHA_CUTOFF
                or raw[(i + 1) * 4 + 3] < ALPHA_CUTOFF
                or raw[(i - w) * 4 + 3] < ALPHA_CUTOFF
                or raw[(i + w) * 4 + 3] < ALPHA_CUTOFF
            ):
                edge[i] = 1

    repainted = 0
    updates: list[tuple[int, int, int, int]] = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if not edge[i]:
                continue
            r = g = b = n = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    j = i + dy * w + dx
                    if j == i or edge[j] or raw[j * 4 + 3] < ALPHA_CUTOFF:
                        continue
                    r += raw[j * 4]
                    g += raw[j * 4 + 1]
                    b += raw[j * 4 + 2]
                    n += 1
            if n:
                updates.append((i, r // n, g // n, b // n))

    for i, r, g, b in updates:
        raw[i * 4] = r
        raw[i * 4 + 1] = g
        raw[i * 4 + 2] = b
        repainted += 1
    return repainted


def _write_png_rgba(path: Path, w: int, h: int, raw: bytes) -> None:
    """Minimal RGBA PNG writer — no Pillow on the target machine."""

    rows = bytearray()
    for y in range(h):
        rows.append(0)  # filter type: none
        rows += raw[y * w * 4 : (y + 1) * w * 4]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def build_frame(src: Path, key: str, crop: tuple[int, int, int, int], gif_out: Path, png_out: Path) -> int:
    x, y, cw, ch = crop
    base = f"{_key_filter(key)},crop={cw}:{ch}:{x}:{y},scale={FRAME_SIZE}:{FRAME_SIZE}:flags=lanczos"
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
        crop = square_crop(union, *_probe_size(src), frame=boxes.get(src))
        sealed = build_frame(src, keys[src], crop, gif, png)
        built.setdefault(state, []).append(gif.name)
        note = f" sealed={sealed}px" if sealed else ""
        print(f"  {skin}/{state}/{src.stem}  key={keys[src]} crop={crop}{note}")

    states = {state: sorted(names) for state, names in built.items()}
    # Bake the rhythm into the manifest so the browser overlay plays the exact
    # same loop as the desktop window instead of reimplementing the timing.
    timelines = {
        state: [list(step) for step in auto_timeline(state, len(names)).steps]
        for state, names in states.items()
    }
    # `crop` is relative because the source stills come back at three different
    # resolutions; each frame resolves it against its own size at build time.
    return {
        "keys": {f"{src.parent.name}/{src.stem}": keys[src] for _state, src in frames},
        "crop_relative": [round(v, 4) for v in union],
        "states": states,
        "timelines": timelines,
    }


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
