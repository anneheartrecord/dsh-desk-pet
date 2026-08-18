"""Frame images, in pure standard library.

This is what `scripts/build_frames.py` used to shell out to ffmpeg for. It lives
here rather than there for one reason: `scripts/` is not published, so anything
left in it is out of reach of the installed package — and installing a skin on a
user's machine needs exactly these operations. The build script imports from
here now, so the geometry the art gate enforces has a single definition.

No ffmpeg, no Pillow, no numpy. `zlib` does the only heavy lifting.

The key is `colorkey`, not `chromakey`: chroma alone ignores luma, and against a
pastel plate that deletes a character's black eyes. Everything is keyed against
a flat magenta plate the generator is told to paint, because no image backend
this project has used has ever returned an alpha channel.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections import deque
from pathlib import Path

FRAME_SIZE = 200
# Distance from the sampled plate colour at which a pixel is background.
# Measured across all five skins, subject coverage is identical at 0.08 and at
# 0.32 and only starts costing art at 0.40, so this sits mid-gap.
SIMILARITY = 0.24
ALPHA_CUTOFF = 160
# Where the bottom of the body sits inside the square crop. Shared by every
# skin so switching skin does not move the pet vertically.
BASELINE_RATIO = 0.94
# How much of the finished frame the character should cover. Sizing by the
# bounding box instead made a round silhouette fill half the frame while a
# long thin one filled a third: the eye reads ink, not extents.
TARGET_COVERAGE = 0.32
SOURCE_PAD_RATIO = 0.3
# Sum-of-channel distance under which an enclosed region counts as plate
# showing through rather than artwork the key removed.
PLATE_DISTANCE = 150

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
# Refuses a hostile or broken header before anything is allocated.
MAX_DIMENSION = 4096
MAX_PIXELS = 4096 * 4096


class ImageError(ValueError):
    """A file we will not decode, with a reason a user can act on."""


def container(data: bytes) -> str:
    """Identify by magic bytes, never by extension.

    The repository's own `assets/source` tree holds eighteen files named `.png`
    that are JPEG. That only ever worked because ffmpeg sniffs content, and a
    strict parser would have called them corrupt PNGs instead of naming the
    format that actually arrived.
    """

    if data[:8] == PNG_MAGIC:
        return "png"
    if data[:3] == JPEG_MAGIC:
        return "jpeg"
    return "unknown"


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


def square_crop(
    union: tuple[float, float, float, float],
    w: int,
    h: int,
    frame: tuple[float, float, float, float] | None = None,
    pad_ratio: float = 0.06,
    area_px: float = 0.0,
) -> tuple[int, int, int, int]:
    """Square crop for one frame: sized from the skin, positioned from the pose.

    Two different jobs, deliberately fed by two different boxes.

    *Size* comes from the skin's drawn area, not its bounding box, so every skin
    reads as the same-sized animal. Sizing by the box made the DeepSeek whale
    fill 52% of its frame against ~30% for the others: it is a round shape that
    nearly fills its own box, where a whale with a raised tail leaves most of
    its box empty. The eye reads ink, not extents. `area_px` is how much of the
    source the character actually covers, and the crop is sized so that lands at
    `TARGET_COVERAGE` of the output.

    *Position* comes from this frame's own box, anchored so the bottom of the
    body lands at `BASELINE_RATIO`. Anchoring on the union instead let each pose
    sit wherever its own extent happened to fall — up to 25px apart within one
    skin, so the pet visibly hopped whenever it changed state. Vertical movement
    is the renderer's job (breath, hop); the art should hold still.
    """

    ux0, uy0, ux1, uy1 = union[0] * w, union[1] * h, union[2] * w, union[3] * h
    box_w, box_h = ux1 - ux0, uy1 - uy0

    if area_px:
        # A crop of `side` shows `area_px` of ink; we want that to be
        # TARGET_COVERAGE of the result, so side = sqrt(area / target).
        side = math.sqrt(area_px / TARGET_COVERAGE)
        # Never crop tighter than the subject itself, whatever the arithmetic
        # says — a pose wider than the target would get its edges cut off.
        side = max(side, box_w * (1 + pad_ratio), box_h * (1 + pad_ratio))
    else:
        side = max(box_w, box_h) * (1 + pad_ratio * 2)
    # Deliberately not clamped to the source size. `build_frame` pads the source
    # with plate colour first, so a crop wider than the original simply picks up
    # background — and clamping here is what kept the DeepSeek whale oversized:
    # its art is drawn large in its own frame, so hitting the target coverage
    # needs a crop bigger than the source it came from.
    side = int(round(min(side, (w + 2 * SOURCE_PAD_RATIO * min(w, h)))))

    box = frame or union
    fx0, fy1 = box[0] * w, box[3] * h
    fx1 = box[2] * w
    cx = (fx0 + fx1) / 2
    # Deliberately unclamped. A pose sitting low in its source needs a crop that
    # runs past the bottom edge, and clamping it back inside pushes the body up
    # the frame instead — which is how the nautilus ended up 16px above every
    # other skin. `build_frame` pads the source first so these offsets are
    # always valid.
    x = int(round(cx - side / 2))
    y = int(round(fy1 - side * BASELINE_RATIO))
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


def decode_png(data: bytes) -> tuple[int, int, bytearray]:
    """Decode 8-bit PNG to (width, height, RGBA).

    The input contract is enforced before anything is allocated, because these
    bytes come from someone else's model on someone else's machine: a header
    can claim dimensions that exhaust memory on the row buffer alone, and a
    small IDAT can inflate into gigabytes.

    Colour types without alpha are accepted on purpose. The plate route needs
    them — that is what every backend actually returns.
    """

    kind = container(data)
    if kind != "png":
        raise ImageError(f"expected a PNG, got {kind}")

    pos, idat = 8, bytearray()
    width = height = depth = ctype = interlace = None
    palette = trns = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        name = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if name == b"IHDR":
            width, height, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body[:13])
            if depth != 8:
                raise ImageError(f"only 8-bit PNG is supported, got {depth}-bit")
            if interlace != 0:
                raise ImageError("interlaced PNG is not supported")
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise ImageError(f"image is {width}x{height}; the limit is {MAX_DIMENSION}")
            if width * height > MAX_PIXELS:
                raise ImageError("image exceeds the pixel budget")
        elif name == b"IDAT":
            idat += body
        elif name == b"PLTE":
            palette = body
        elif name == b"tRNS":
            trns = body
        elif name == b"IEND":
            break
    if width is None:
        raise ImageError("no IHDR chunk")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ImageError(f"unsupported colour type {ctype}")

    stride = width * channels
    expected = height * (stride + 1)
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(bytes(idat), expected)
    if decompressor.unconsumed_tail:
        raise ImageError("compressed data expands beyond the declared image size")
    if len(raw) < expected:
        raise ImageError("truncated image data")

    out = bytearray(stride * height)
    prev = bytearray(stride)
    i = 0
    for y in range(height):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if f == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                c = prev[x - channels] if x >= channels else 0
                b = prev[x]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        elif f != 0:
            raise ImageError(f"unknown row filter {f}")
        out[y * stride:(y + 1) * stride] = line
        prev = line

    if ctype == 6:
        return width, height, out
    rgba = bytearray(width * height * 4)
    for p in range(width * height):
        if ctype == 2:
            r, g, b = out[p * 3:p * 3 + 3]
            a = 255
        elif ctype == 0:
            r = g = b = out[p]
            a = 255
        elif ctype == 4:
            r = g = b = out[p * 2]
            a = out[p * 2 + 1]
        else:
            index = out[p]
            r, g, b = palette[index * 3:index * 3 + 3]
            a = trns[index] if trns and index < len(trns) else 255
        rgba[p * 4:p * 4 + 4] = bytes((r, g, b, a))
    return width, height, rgba


def sample_plate(raw: bytearray, w: int, h: int) -> tuple[int, int, int]:
    """The plate colour, taken as the median of the four corners.

    Median rather than mean: a corner clipped by the artwork cannot drag the
    key. Sampled per frame because each generation returns a slightly different
    magenta.
    """

    patch = max(1, min(w, h) // 40)
    samples = []
    for ox, oy in ((0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)):
        i = ((oy * w) + ox) * 4
        samples.append((raw[i], raw[i + 1], raw[i + 2]))
    return tuple(sorted(c[k] for c in samples)[len(samples) // 2] for k in range(3))


def color_key(raw: bytearray, w: int, h: int, plate: tuple[int, int, int],
              similarity: float = SIMILARITY) -> int:
    """Zero alpha wherever the pixel is close to the plate. Returns pixels cleared.

    RGB is left untouched on purpose: `_seal_interior` judges an enclosed
    region by the colour that survives underneath, which is the only thing that
    tells a hole cut out of the artwork apart from real background.
    """

    limit = (similarity * 255.0) * 3.0
    cleared = 0
    pr, pg, pb = plate
    for i in range(0, len(raw), 4):
        if abs(raw[i] - pr) + abs(raw[i + 1] - pg) + abs(raw[i + 2] - pb) <= limit:
            if raw[i + 3]:
                cleared += 1
            raw[i + 3] = 0
    return cleared


def alpha_bounds(raw: bytearray, w: int, h: int,
                 cutoff: int = ALPHA_CUTOFF) -> tuple[tuple[float, float, float, float] | None, float]:
    """Relative body box and opaque coverage.

    Relative because sources do not share a resolution. Rows and columns
    holding only a handful of opaque pixels are ignored, so scattered sparkles
    and ZZZ glyphs near the edge cannot zoom every other frame of the skin out
    to match them.
    """

    row_counts = [0] * h
    col_counts = [0] * w
    opaque = 0
    for y in range(h):
        base = y * w * 4
        for x in range(w):
            if raw[base + x * 4 + 3] >= cutoff:
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


def crop_scale(raw: bytearray, w: int, h: int, box: tuple[int, int, int, int],
               size: int = FRAME_SIZE) -> bytearray:
    """Crop a square and box-filter it down, premultiplying by alpha.

    Averaging colour weighted by alpha stops transparent pixels dragging the
    edges toward black, which is what a naive mean does to an antialiased
    silhouette.
    """

    sx, sy, side, _ = box
    out = bytearray(size * size * 4)
    step = side / size
    for oy in range(size):
        y0 = int(sy + oy * step)
        y1 = max(y0 + 1, int(sy + (oy + 1) * step))
        for ox in range(size):
            x0 = int(sx + ox * step)
            x1 = max(x0 + 1, int(sx + (ox + 1) * step))
            r = g = b = a = n = 0
            for yy in range(y0, y1):
                if yy < 0 or yy >= h:
                    continue
                base = yy * w * 4
                for xx in range(x0, x1):
                    if xx < 0 or xx >= w:
                        continue
                    i = base + xx * 4
                    al = raw[i + 3]
                    r += raw[i] * al
                    g += raw[i + 1] * al
                    b += raw[i + 2] * al
                    a += al
                    n += 1
            if not n:
                continue
            o = (oy * size + ox) * 4
            if a:
                out[o] = r // a
                out[o + 1] = g // a
                out[o + 2] = b // a
            out[o + 3] = a // n
    return out
