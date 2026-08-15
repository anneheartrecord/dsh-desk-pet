"""Frame timelines and the motion applied on top of them.

Two ideas, both borrowed from how the Codex pet atlas is timed:

* A loop is a list of ``(frame_index, hold_ms)`` steps, not a fixed frame rate.
  Uniform timing is what makes a sprite read as a flipbook; uneven timing is
  what makes it read as breathing. A two-frame idle with holds of
  ``2400/120/240/120`` is a double blink, and needs no extra art.
* Position is a function of the clock, not of the frame. A slow sine on Y is a
  breath; a lean toward the cursor is attention. Both survive a single-frame
  state, which is what keeps `working` and `error` from looking dead.

Everything here is pure: no Tk, no disk. That is deliberate — it is the only
layer of the pet that can be asserted on in a headless test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Step = tuple[int, int]  # (frame index, hold in ms)

# Hand-tuned holds. Anything not listed falls back to `auto_timeline`.
BLINK_MS = 120


@dataclass(frozen=True)
class Timeline:
    """A looping sequence of holds over frame indices."""

    steps: tuple[Step, ...]

    @property
    def total_ms(self) -> int:
        return sum(ms for _index, ms in self.steps)

    def frame_at(self, elapsed_ms: int) -> int:
        """Index of the frame showing at ``elapsed_ms``. Loops forever."""

        if not self.steps:
            return 0
        total = self.total_ms
        if total <= 0:
            return self.steps[0][0]
        t = elapsed_ms % total
        for index, ms in self.steps:
            if t < ms:
                return index
            t -= ms
        return self.steps[-1][0]


def auto_timeline(state: str, frame_count: int) -> Timeline:
    """Pick a believable rhythm for however many frames a state actually has.

    Art arrives incrementally, so this has to degrade rather than fail: one
    frame is a still that the breath still animates, two frames become a blink,
    and more than two become a real loop with a longer hold on the rest pose.
    """

    if frame_count <= 0:
        return Timeline(())
    if frame_count == 1:
        return Timeline(((0, 400),))

    if frame_count == 2:
        # Frame 1 is the closed-eye/off pose in every pack we generate.
        if state == "idle":
            return Timeline(((0, 2400), (1, BLINK_MS), (0, 240), (1, BLINK_MS)))
        if state == "sleeping":
            return Timeline(((0, 1800), (1, 1800)))
        if state == "working":
            return Timeline(((0, 260), (1, 260)))
        if state == "waiting":
            return Timeline(((0, 520), (1, 320)))
        if state == "error":
            return Timeline(((0, 900), (1, 220)))
        return Timeline(((0, 500), (1, 260)))

    if frame_count == 3 and state == "idle":
        # Frame 2 is the half-lidded in-between. Playing it on the way down and
        # again on the way up is what turns a two-frame cut into an eyelid; the
        # Codex atlas spends its two shortest holds on exactly this frame.
        return Timeline(
            (
                (0, 2400), (2, 60), (1, BLINK_MS), (2, 60),
                (0, 300), (2, 60), (1, BLINK_MS), (2, 60),
            )
        )

    rest_hold = 600 if state in ("idle", "sleeping") else 220
    steps: list[Step] = [(0, rest_hold)]
    steps.extend((i, 140) for i in range(1, frame_count))
    return Timeline(tuple(steps))


@dataclass(frozen=True)
class Motion:
    """Where to draw the sprite this tick, relative to its resting spot."""

    dx: float
    dy: float
    # Kept separate from dy so a caller can tell a breath from a hop.
    hop: float = 0.0


# amplitude px, period ms — per state, so the body language differs even when
# two states share one still image.
_BREATH = {
    "idle": (2.6, 2900),
    "working": (1.6, 1100),
    "waiting": (3.2, 2000),
    "error": (1.1, 5200),
    "happy": (4.0, 620),
    "sleeping": (3.4, 4600),
}
LEAN_MAX_PX = 5.0


def breath_offset(state: str, elapsed_ms: int) -> float:
    amplitude, period = _BREATH.get(state, _BREATH["idle"])
    return amplitude * math.sin(2 * math.pi * (elapsed_ms % period) / period)


def lean_offset(pointer_dx: float | None, half_width: float) -> float:
    """Nudge the body toward the cursor.

    The sprites are pre-rendered, so real eye-follow is out; a small lean buys
    most of the same "it noticed me" read for none of the art budget. Clamped
    hard, because past a few pixels it stops looking like attention and starts
    looking like drift.
    """

    if pointer_dx is None or half_width <= 0:
        return 0.0
    ratio = max(-1.0, min(1.0, pointer_dx / (half_width * 6)))
    return ratio * LEAN_MAX_PX


def motion_for(
    state: str,
    elapsed_ms: int,
    *,
    pointer_dx: float | None = None,
    half_width: float = 100.0,
    hop_until_ms: int = 0,
    now_ms: int = 0,
) -> Motion:
    dy = breath_offset(state, elapsed_ms)
    dx = lean_offset(pointer_dx, half_width)
    hop = 0.0
    if hop_until_ms and now_ms < hop_until_ms:
        # One decaying bounce, used as the click/greet reaction.
        remaining = (hop_until_ms - now_ms) / 520
        hop = -14.0 * math.sin(math.pi * min(1.0, max(0.0, remaining))) * remaining
    return Motion(dx=dx, dy=dy + hop, hop=hop)


def sequence_frames(timeline: Timeline, step_ms: int, span_ms: int) -> Sequence[int]:
    """Sample a timeline — used by tests to assert a loop actually changes."""

    return [timeline.frame_at(t) for t in range(0, span_ms, step_ms)]
