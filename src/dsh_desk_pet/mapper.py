"""Map observed or injected agent activity onto the four display states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PetState = Literal["idle", "working", "waiting", "error"]

STATES: tuple[PetState, ...] = ("idle", "working", "waiting", "error")

_WORKING = frozenset({"running", "in_progress", "working", "active", "tool"})
_WAITING = frozenset({"waiting", "waiting_user", "blocked", "approval", "needs_input"})
_ERROR = frozenset({"error", "failed", "errored", "fail"})
_IDLE = frozenset({"", "none", "idle", "completed", "complete", "done", "success"})


@dataclass(frozen=True)
class AgentActivity:
    """A single snapshot of what the coding agent is doing.

    ``kind`` is a coarse label. Tests and the desktop observer both construct
    this object; the mapper does not read DSH files itself.
    """

    kind: str


def map_activity(activity: AgentActivity | None) -> PetState:
    """Return one of idle / working / waiting / error.

    No activity, empty activity, and a completed run all map to idle.
    Unknown labels also fall back to idle so a stale observer cannot invent
    a fifth state.
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
    return "idle"
