"""Shared four-state scenes. Each skin is a different silhouette and palette."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

Shape = Literal["oval", "polygon", "line"]


@dataclass(frozen=True)
class DrawCmd:
    shape: Shape
    coords: tuple[float, ...]
    fill: str = ""
    outline: str = ""
    width: float = 1.0


CANVAS_W = 168
CANVAS_H = 188
PICKER_Y = 168


def _oval(x0: float, y0: float, x1: float, y1: float, fill: str, outline: str = "", width: float = 1.0) -> DrawCmd:
    return DrawCmd("oval", (x0, y0, x1, y1), fill=fill, outline=outline, width=width)


def _poly(points: Sequence[float], fill: str, outline: str = "", width: float = 1.0) -> DrawCmd:
    return DrawCmd("polygon", tuple(points), fill=fill, outline=outline, width=width)


def _line(*xy: float, fill: str, width: float = 2.0) -> DrawCmd:
    return DrawCmd("line", tuple(xy), fill=fill, outline=fill, width=width)


def _eyes(cx: float, cy: float, *, look: float = 0.0, worried: bool = False) -> list[DrawCmd]:
    pupil = "#1a1a1a"
    white = "#fff8ee"
    cmds = [
        _oval(cx - 18, cy - 8, cx - 4, cy + 6, white, "#1a1a1a", 1.2),
        _oval(cx + 4, cy - 8, cx + 18, cy + 6, white, "#1a1a1a", 1.2),
        _oval(cx - 13 + look, cy - 4, cx - 8 + look, cy + 2, pupil),
        _oval(cx + 9 + look, cy - 4, cx + 14 + look, cy + 2, pupil),
    ]
    if worried:
        cmds.append(_line(cx - 18, cy - 12, cx - 6, cy - 9, fill="#1a1a1a", width=2))
        cmds.append(_line(cx + 6, cy - 9, cx + 18, cy - 12, fill="#1a1a1a", width=2))
    return cmds


def _whale(state: str) -> list[DrawCmd]:
    body = "#2f6feb"
    belly = "#dce9ff"
    accent = "#123a8c"
    if state == "error":
        body, belly, accent = "#c44536", "#f6d0c8", "#7a1d14"
    elif state == "waiting":
        body, belly, accent = "#3d8fd4", "#e8f3ff", "#1b4f86"
    elif state == "working":
        body, belly, accent = "#255ad4", "#c9dbff", "#0d2f78"

    y_shift = 4 if state == "idle" else 0
    tail = (18, 78 + y_shift, 48, 92 + y_shift, 18, 108 + y_shift, 36, 92 + y_shift)
    cmds = [
        _poly(tail, body, accent, 1.5),
        _oval(44, 52 + y_shift, 148, 128 + y_shift, body, accent, 1.8),
        _oval(72, 86 + y_shift, 138, 122 + y_shift, belly),
        _poly((78, 118 + y_shift, 96, 136 + y_shift, 112, 118 + y_shift), body, accent, 1.2),
    ]
    look = 4 if state == "waiting" else 0
    cmds.extend(_eyes(96, 72 + y_shift, look=look, worried=state == "error"))
    if state == "working":
        cmds.append(_line(150, 70, 162, 62, 150, 54, fill=accent, width=3))
        cmds.append(_line(152, 88, 164, 88, fill=accent, width=3))
    if state == "waiting":
        cmds.append(_line(84, 36, 84, 20, 96, 28, fill="#f0c14a", width=3))
    if state == "error":
        cmds.append(_poly((108, 40, 124, 28, 132, 44), "#f0c14a", "#7a1d14", 1.2))
    return cmds


def _threadcore(state: str) -> list[DrawCmd]:
    coil = "#d9822b"
    tight = "#b45309"
    loose = "#f3c77a"
    if state == "error":
        coil, tight, loose = "#b42318", "#7a120c", "#f5b5ad"
    elif state == "waiting":
        coil, tight, loose = "#e09a3a", "#c56a10", "#ffe0a3"
    cmds = []
    radii = (54, 42, 30, 18) if state != "working" else (48, 36, 24, 12)
    for i, r in enumerate(radii):
        color = coil if i % 2 == 0 else tight
        cmds.append(_oval(84 - r, 88 - r, 84 + r, 88 + r, "", color, 5 if state != "idle" else 3.5))
    cmds.append(_oval(70, 74, 98, 102, loose, tight, 1.5))
    look = 5 if state == "waiting" else 0
    cmds.extend(_eyes(84, 86, look=look, worried=state == "error"))
    if state == "waiting":
        cmds.append(_line(132, 88, 156, 72, fill=coil, width=4))
        cmds.append(_oval(152, 64, 164, 76, "#fff8ee", coil, 1.5))
    if state == "error":
        cmds.append(_line(50, 50, 118, 126, fill="#7a120c", width=3))
        cmds.append(_line(118, 50, 50, 126, fill="#7a120c", width=3))
    if state == "working":
        cmds.append(_line(84, 28, 84, 40, fill=tight, width=3))
        cmds.append(_line(128, 56, 138, 46, fill=tight, width=3))
    return cmds


def _nautilus(state: str) -> list[DrawCmd]:
    shell = "#e8c39e"
    ridge = "#b56b3a"
    inner = "#f6e6d0"
    if state == "error":
        shell, ridge, inner = "#d9897a", "#8b2e22", "#f3d0c8"
    elif state == "working":
        shell, ridge, inner = "#d9b07a", "#8f4d22", "#f3ddb8"
    cmds = [
        _oval(40, 48, 140, 148, shell, ridge, 2),
        _oval(62, 70, 128, 136, inner, ridge, 1.2),
        _oval(78, 86, 118, 126, shell, ridge, 1.2),
        _oval(90, 98, 112, 120, inner, ridge, 1),
    ]
    look = 4 if state == "waiting" else 0
    cmds.extend(_eyes(92, 78, look=look, worried=state == "error"))
    if state == "working":
        cmds.append(_line(132, 72, 150, 56, fill=ridge, width=3))
        cmds.append(_line(136, 96, 154, 96, fill=ridge, width=3))
    if state == "waiting":
        cmds.append(_poly((36, 108, 18, 96, 22, 120), ridge, ridge, 1))
    if state == "error":
        cmds.append(_line(56, 60, 124, 136, fill="#8b2e22", width=2.5))
    return cmds


def _jellyfish(state: str) -> list[DrawCmd]:
    cap = "#c7b4f0"
    organ = "#7c5cbf"
    tent = "#9b84d6"
    if state == "error":
        cap, organ, tent = "#e3a0b0", "#a33b55", "#c56b7e"
    elif state == "working":
        cap, organ, tent = "#b39ae8", "#5b3ea8", "#8a6fd0"
    y = 6 if state == "idle" else 0
    cmds = [
        _oval(46, 40 + y, 122, 96 + y, cap, organ, 1.6),
        _oval(64, 58 + y, 84, 80 + y, organ),
        _oval(86, 56 + y, 104, 78 + y, "#efe6ff"),
    ]
    # tentacles: idle hang loose, working pull in, waiting reach forward, error tangle
    if state == "idle":
        cmds.extend(
            [
                _line(62, 92 + y, 56, 140, fill=tent, width=2.4),
                _line(84, 96 + y, 84, 148, fill=tent, width=2.4),
                _line(106, 92 + y, 114, 140, fill=tent, width=2.4),
            ]
        )
    elif state == "working":
        cmds.extend(
            [
                _line(64, 90, 70, 128, fill=tent, width=2.6),
                _line(84, 94, 84, 132, fill=tent, width=2.6),
                _line(104, 90, 98, 128, fill=tent, width=2.6),
            ]
        )
    elif state == "waiting":
        cmds.extend(
            [
                _line(64, 92, 40, 120, fill=tent, width=2.6),
                _line(84, 96, 84, 134, fill=tent, width=2.6),
                _line(108, 92, 148, 78, fill="#f0c14a", width=3),
            ]
        )
    else:
        cmds.extend(
            [
                _line(62, 92, 110, 136, fill=tent, width=2.6),
                _line(108, 92, 58, 140, fill=tent, width=2.6),
                _line(84, 96, 84, 148, fill=organ, width=2.6),
            ]
        )
    look = 5 if state == "waiting" else 0
    cmds.extend(_eyes(84, 62 + y, look=look, worried=state == "error"))
    return cmds


_PAINTERS = {
    "whale": _whale,
    "threadcore": _threadcore,
    "nautilus": _nautilus,
    "jellyfish": _jellyfish,
}

BACKGROUND = "#f4efe6"


def scene_for(skin_id: str, state: str) -> list[DrawCmd]:
    painter = _PAINTERS.get(skin_id, _whale)
    return painter(state)


def picker_dots(selected: str) -> list[tuple[str, float, float, float, float, str, bool]]:
    """Return (skin_id, x0, y0, x1, y1, color, selected) for the four chips."""

    colors = {
        "whale": "#2f6feb",
        "threadcore": "#d9822b",
        "nautilus": "#b56b3a",
        "jellyfish": "#7c5cbf",
    }
    order = ("whale", "threadcore", "nautilus", "jellyfish")
    dots = []
    x = 28
    for skin_id in order:
        dots.append((skin_id, x, PICKER_Y, x + 16, PICKER_Y + 16, colors[skin_id], skin_id == selected))
        x += 34
    return dots
