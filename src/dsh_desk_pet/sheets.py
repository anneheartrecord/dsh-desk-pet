"""Render one skin's six states into a single shareable image.

This ships rather than living in `scripts/` because the people who most need
it never clone the repository: someone who made a skin from a photo installed
this through npm, and asking them to check out a build tree to produce one
preview image is where sharing it stops.

Standard library only, like the rest of the frame path — the point of the
zero-dependency pipeline is that it works on the machine that generated the
skin, not just on a machine set up to build this project.
"""

from __future__ import annotations

from pathlib import Path

from . import imaging, packs

STATE_ORDER = ("idle", "working", "waiting", "error", "happy", "sleeping")
CELL = 180
GAP = 16
PAD = 20
PLATE = (0x0D, 0x0D, 0x12)


class SheetError(Exception):
    """A skin that cannot be drawn — unknown id, or no frames on disk."""


def _blank(width: int, height: int) -> bytearray:
    return bytearray(bytes((*PLATE, 255)) * width * height)


def _composite(dst: bytearray, dst_w: int, src, src_w: int, src_h: int,
               x0: int, y0: int) -> None:
    """Alpha-blend one decoded RGBA image onto the plate.

    Blended rather than copied: the frames carry a soft keyed edge, and
    dropping it on with a hard copy leaves the halo the keying removed.
    """

    for y in range(src_h):
        drow = (y0 + y) * dst_w
        for x in range(src_w):
            s = (y * src_w + x) * 4
            alpha = src[s + 3]
            if not alpha:
                continue
            d = (drow + x0 + x) * 4
            if alpha == 255:
                dst[d:d + 4] = bytes(src[s:s + 4])
            else:
                for c in range(3):
                    dst[d + c] = (src[s + c] * alpha + dst[d + c] * (255 - alpha)) // 255


def frame_image(skin_id: str, state: str, index: int = 0):
    """Decode one frame, scaled to the cell, as (pixels, width, height)."""

    frames = packs.frames_for(skin_id, state, web=True)
    if not frames:
        raise SheetError(f"{skin_id}/{state} has no frames")
    path = frames[min(index, len(frames) - 1)]
    width, height, pixels = imaging.decode_png(path.read_bytes())
    if (width, height) != (CELL, CELL):
        pixels = imaging.crop_scale(pixels, width, height, (0, 0, width, height), CELL)
        width = height = CELL
    return pixels, width, height


def build_strip(skin_id: str, out: Path) -> Path:
    """Write a one-row sheet: the first frame of every state this skin has."""

    states = [s for s in STATE_ORDER if packs.frames_for(skin_id, s, web=True)]
    if not states:
        raise SheetError(
            f"no frames for skin {skin_id!r} — check the id with --inventory")

    width = PAD * 2 + CELL * len(states) + GAP * (len(states) - 1)
    height = PAD * 2 + CELL
    plate = _blank(width, height)
    for i, state in enumerate(states):
        pixels, w, h = frame_image(skin_id, state)
        _composite(plate, width, pixels, w, h, PAD + i * (CELL + GAP), PAD)

    out.parent.mkdir(parents=True, exist_ok=True)
    imaging._write_png_rgba(out, width, height, bytes(plate))
    return out
