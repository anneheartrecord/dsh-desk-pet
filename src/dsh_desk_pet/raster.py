"""Rasterize a scene to RGB bytes and optional PNG. Used for screenshots and tests."""

from __future__ import annotations

import struct
import zlib
from typing import Iterable

from .scene import CANVAS_H, CANVAS_W, DrawCmd, scene_for

Color = tuple[int, int, int]


def _hex_rgb(value: str) -> Color:
    raw = value.lstrip("#")
    if len(raw) != 6:
        return (0, 0, 0)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _blend(dst: bytearray, index: int, color: Color, alpha: float = 1.0) -> None:
    if alpha >= 1.0:
        dst[index] = color[0]
        dst[index + 1] = color[1]
        dst[index + 2] = color[2]
        return
    inv = 1.0 - alpha
    dst[index] = int(dst[index] * inv + color[0] * alpha)
    dst[index + 1] = int(dst[index + 1] * inv + color[1] * alpha)
    dst[index + 2] = int(dst[index + 2] * inv + color[2] * alpha)


class Frame:
    def __init__(self, width: int = CANVAS_W, height: int = CANVAS_H, background: str = "#f4efe6") -> None:
        self.width = width
        self.height = height
        fill = _hex_rgb(background)
        self.pixels = bytearray(fill * (width * height))

    def _index(self, x: int, y: int) -> int | None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return None
        return (y * self.width + x) * 3

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        index = self._index(x, y)
        if index is None:
            return
        _blend(self.pixels, index, color)

    def fill_ellipse(self, x0: float, y0: float, x1: float, y1: float, color: Color) -> None:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        rx = abs(x1 - x0) / 2.0
        ry = abs(y1 - y0) / 2.0
        if rx < 0.5 or ry < 0.5:
            return
        min_x = max(0, int(x0))
        max_x = min(self.width - 1, int(x1))
        min_y = max(0, int(y0))
        max_y = min(self.height - 1, int(y1))
        rx2 = rx * rx
        ry2 = ry * ry
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                nx = (x + 0.5 - cx) ** 2 / rx2
                ny = (y + 0.5 - cy) ** 2 / ry2
                if nx + ny <= 1.0:
                    self.set_pixel(x, y, color)

    def stroke_ellipse(self, x0: float, y0: float, x1: float, y1: float, color: Color, width: float) -> None:
        # Draw as a thicker ring by two ellipses is messy; sample a band.
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        rx = abs(x1 - x0) / 2.0
        ry = abs(y1 - y0) / 2.0
        if rx < 0.5 or ry < 0.5:
            return
        outer = 1.0 + (width / max(rx, ry))
        inner = max(0.0, 1.0 - (width / max(rx, ry)))
        min_x = max(0, int(x0 - width))
        max_x = min(self.width - 1, int(x1 + width))
        min_y = max(0, int(y0 - width))
        max_y = min(self.height - 1, int(y1 + width))
        rx2 = rx * rx
        ry2 = ry * ry
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                nx = (x + 0.5 - cx) ** 2 / rx2
                ny = (y + 0.5 - cy) ** 2 / ry2
                d = nx + ny
                if inner <= d <= outer:
                    self.set_pixel(x, y, color)

    def fill_polygon(self, coords: tuple[float, ...], color: Color) -> None:
        pts = [(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]
        if len(pts) < 3:
            return
        min_x = max(0, int(min(p[0] for p in pts)))
        max_x = min(self.width - 1, int(max(p[0] for p in pts)))
        min_y = max(0, int(min(p[1] for p in pts)))
        max_y = min(self.height - 1, int(max(p[1] for p in pts)))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if _point_in_poly(x + 0.5, y + 0.5, pts):
                    self.set_pixel(x, y, color)

    def stroke_line(self, coords: tuple[float, ...], color: Color, width: float) -> None:
        for i in range(0, len(coords) - 3, 2):
            _draw_thick_line(self, coords[i], coords[i + 1], coords[i + 2], coords[i + 3], color, width)

    def paint(self, commands: Iterable[DrawCmd]) -> None:
        for cmd in commands:
            if cmd.shape == "oval":
                x0, y0, x1, y1 = cmd.coords
                if cmd.fill:
                    self.fill_ellipse(x0, y0, x1, y1, _hex_rgb(cmd.fill))
                if cmd.outline:
                    self.stroke_ellipse(x0, y0, x1, y1, _hex_rgb(cmd.outline), cmd.width)
            elif cmd.shape == "polygon":
                if cmd.fill:
                    self.fill_polygon(cmd.coords, _hex_rgb(cmd.fill))
                if cmd.outline and cmd.outline != cmd.fill:
                    # outline via connecting edges
                    pts = cmd.coords
                    closed = pts + pts[:2]
                    self.stroke_line(closed, _hex_rgb(cmd.outline), cmd.width)
            elif cmd.shape == "line":
                self.stroke_line(cmd.coords, _hex_rgb(cmd.fill or cmd.outline), cmd.width)

    def to_png(self) -> bytes:
        raw = bytearray()
        row = self.width * 3
        for y in range(self.height):
            raw.append(0)
            start = y * row
            raw.extend(self.pixels[start : start + row])
        compressed = zlib.compress(bytes(raw), 9)
        return _png_wrap(self.width, self.height, compressed)


def _point_in_poly(x: float, y: float, pts: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def _draw_thick_line(frame: Frame, x0: float, y0: float, x1: float, y1: float, color: Color, width: float) -> None:
    steps = max(int(max(abs(x1 - x0), abs(y1 - y0)) * 2), 1)
    radius = max(int(width / 2), 1)
    for i in range(steps + 1):
        t = i / steps
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius + 1:
                    frame.set_pixel(int(cx) + dx, int(cy) + dy, color)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _png_wrap(width: int, height: int, compressed: bytes) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def render_png(skin_id: str, state: str) -> bytes:
    frame = Frame()
    frame.paint(scene_for(skin_id, state))
    return frame.to_png()


def pixel_checksum(skin_id: str, state: str) -> int:
    frame = Frame()
    frame.paint(scene_for(skin_id, state))
    return zlib.crc32(bytes(frame.pixels)) & 0xFFFFFFFF
