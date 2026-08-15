"""Map observed or injected agent activity onto the display states.

`completed` deliberately does not land on idle. A run finishing is the one
moment the pet has something to say, so it maps to `happy` and the runtime
decays that back to idle on a timer — the same shape as the Codex pet's
one-shot `waving` row, which plays once and returns to the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PetState = Literal["idle", "working", "waiting", "error", "happy", "sleeping"]

STATES: tuple[PetState, ...] = ("idle", "working", "waiting", "error", "happy", "sleeping")

# States the observer can put the pet into directly. `happy` and `sleeping` are
# reached through the runtime's own timers, never straight off an activity.
OBSERVED_STATES: tuple[PetState, ...] = ("idle", "working", "waiting", "error", "happy")

_WORKING = frozenset({"running", "in_progress", "working", "active", "tool", "thinking", "stream"})
_WAITING = frozenset({"waiting", "waiting_user", "blocked", "approval", "needs_input", "permission", "confirm"})
_ERROR = frozenset({"error", "failed", "errored", "fail", "aborted", "cancelled"})
_HAPPY = frozenset({"completed", "complete", "done", "success", "finished", "ok"})
_IDLE = frozenset({"", "none", "idle", "ready"})


@dataclass(frozen=True)
class AgentActivity:
    """A single snapshot of what the coding agent is doing.

    ``kind`` is a coarse label. Tests and the desktop observer both construct
    this object; the mapper does not read DSH files itself.
    """

    kind: str


def map_activity(activity: AgentActivity | None) -> PetState:
    """Return one of idle / working / waiting / error / happy.

    Unknown labels fall back to idle so a stale observer cannot invent a state
    the art packs have never heard of.
    """

    if activity is None:
        return "idle"
    kind = (activity.kind or "").strip().lower()
    if kind in _IDLE:
        return "idle"
    if kind in _WORKING:
        return "working"
    if kind in _WAITING:
        return "waiting"
    if kind in _ERROR:
        return "error"
    if kind in _HAPPY:
        return "happy"
    return "idle"
