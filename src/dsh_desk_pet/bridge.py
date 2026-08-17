"""Publish what the desktop pet is doing so the in-page overlay can mirror it.

There are two pets — a Tk window and a `<div>` injected into the DSH page — and
only one of them can watch the agent. Running the observer twice would let them
disagree, and polling DSH from Node would mean a second implementation of the
same heuristics. So the desktop process is the single authority: it writes a
tiny JSON file, and the plugin's HTTP route just reads it back out.

The write is atomic (temp file + rename) because the route may read it mid-write
at any moment, and a half-written file would show up as a parse error in the
browser rather than a stale-but-valid state.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

STATE_DIRNAME = ".dsh-desk-pet"
STATE_FILENAME = "state.json"

# The desktop pet republishes on every state change and at least once per
# heartbeat; anything older than this is a file a dead process left behind.
STALE_AFTER_MS = 6000


def state_path(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / STATE_DIRNAME / STATE_FILENAME


def publish(skin_id: str, state: str, *, home: Path | None = None, epoch_ms: int = 0) -> Path:
    """Write the current skin/state. Returns the path written.

    `wall_ms` is deliberately wall-clock, not the monotonic `epoch_ms` the
    renderer runs on: the reader is a Node process that only has `Date.now()`,
    and a process-relative timestamp gives it no way to tell a live pet from
    the file a killed one left behind. `pid` lets the reader check the same
    thing a second way, and doubles as a single-instance marker.
    """

    path = state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "skin": skin_id,
        "state": state,
        "epoch_ms": epoch_ms,
        "wall_ms": int(time.time() * 1000),
        "pid": os.getpid(),
    }
    blob = json.dumps(payload, separators=(",", ":"))

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(blob)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def read(home: Path | None = None) -> dict:
    """Read back the published state. Never raises — a missing pet is just idle."""

    path = state_path(home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"skin": "deepseek", "state": "idle", "epoch_ms": 0}
    if not isinstance(payload, dict):
        return {"skin": "deepseek", "state": "idle", "epoch_ms": 0}
    return payload


def clear(home: Path | None = None) -> None:
    """Remove the file so a stale state cannot outlive the process."""

    state_path(home).unlink(missing_ok=True)


def live_pid(home: Path | None = None, *, now_ms: int | None = None) -> int | None:
    """PID of a pet that is currently running, if there is one.

    Two DSH profiles both launch the plugin, and two pets then fight over one
    state file — the page ends up showing whichever wrote last. Freshness alone
    is not enough to detect that (a pet killed a second ago still looks fresh),
    and a live PID alone is not either (PIDs get reused), so this wants both.
    """

    payload = read(home)
    pid = payload.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None

    wall = payload.get("wall_ms")
    if not isinstance(wall, (int, float)):
        return None
    clock = int(time.time() * 1000) if now_ms is None else now_ms
    if clock - wall > STALE_AFTER_MS:
        return None

    try:
        os.kill(pid, 0)  # signal 0 tests for existence without touching it
    except (OSError, ProcessLookupError):
        return None
    return pid
