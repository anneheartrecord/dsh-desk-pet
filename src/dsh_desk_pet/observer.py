"""Optional live DSH observation. Missing DSH stays idle."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable

from .mapper import AgentActivity

# Process name fragments that mean a DSH runtime is up.
_DSH_PROC_MARKERS = ("@deepseek-ai/dsh", "deepseek-harness", "/dsh ", " dsh web", "dsh-desk-pet")


def default_dsh_home() -> Path:
    override = os.environ.get("DSH_HOME")
    if override:
        return Path(override)
    return Path.home() / ".dsh"


def activity_from_env() -> AgentActivity | None:
    raw = os.environ.get("DSH_PET_ACTIVITY")
    if raw is None or raw == "":
        return None
    return AgentActivity(kind=raw)


def activity_from_file(path: Path) -> AgentActivity | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        kind = payload.get("kind") or payload.get("status") or payload.get("state")
        if not kind:
            return None
        return AgentActivity(kind=str(kind))
    return AgentActivity(kind=text.splitlines()[0].strip())


def _newest_session_mtime(home: Path) -> float | None:
    sessions = home / "sessions"
    if not sessions.is_dir():
        return None
    newest: float | None = None
    try:
        for dirpath, _dirnames, filenames in os.walk(sessions):
            for name in filenames:
                if name.startswith("."):
                    continue
                try:
                    mtime = (Path(dirpath) / name).stat().st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
    except OSError:
        return None
    return newest


def _dsh_process_running(markers: Iterable[str] | None = None) -> bool:
    markers = tuple(markers or _DSH_PROC_MARKERS)
    try:
        # Late import: tests can monkeypatch this function instead of spawning ps.
        import subprocess

        result = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in result.stdout.splitlines():
        # Ignore this pet itself so a probe run does not look like a DSH agent.
        if "dsh_desk_pet" in line or "dsh-desk-pet" in line:
            continue
        lowered = line.lower()
        if any(marker.lower() in lowered for marker in markers):
            return True
    return False


def _kind_from_session_tail(home: Path) -> str | None:
    """Best-effort read of the newest session hint file (plain json/jsonl)."""

    sessions = home / "sessions"
    if not sessions.is_dir():
        return None
    newest_path: Path | None = None
    newest_mtime = -1.0
    try:
        for dirpath, _dirnames, filenames in os.walk(sessions):
            for name in filenames:
                if not name.endswith((".json", ".jsonl", ".txt")):
                    continue
                path = Path(dirpath) / name
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_path = path
    except OSError:
        return None
    if newest_path is None:
        return None
    try:
        text = newest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    last_kind: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("kind", "type", "status", "state", "event"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                last_kind = value
    return last_kind


def observe_activity(
    *,
    home: Path | None = None,
    inject_path: Path | None = None,
    now: float | None = None,
    process_running: bool | None = None,
    recent_seconds: float = 15.0,
) -> AgentActivity:
    """Build an AgentActivity from env, an inject file, or local DSH signals.

    When nothing is present the result is ``kind="none"`` so the mapper stays idle.
    """

    env_activity = activity_from_env()
    if env_activity is not None:
        return env_activity

    if inject_path is not None:
        injected = activity_from_file(inject_path)
        if injected is not None:
            return injected

    dsh_home = home if home is not None else default_dsh_home()
    hint = dsh_home / "pet-activity.json"
    hinted = activity_from_file(hint)
    if hinted is not None:
        return hinted

    tail_kind = _kind_from_session_tail(dsh_home)
    if tail_kind:
        lowered = tail_kind.lower()
        if any(token in lowered for token in ("error", "fail")):
            return AgentActivity(kind="error")
        if any(token in lowered for token in ("wait", "approv", "input", "block")):
            return AgentActivity(kind="waiting")
        if any(token in lowered for token in ("run", "tool", "step", "work", "model")):
            return AgentActivity(kind="working")

    running = _dsh_process_running() if process_running is None else process_running
    newest = _newest_session_mtime(dsh_home)
    clock = time.time() if now is None else now
    recently_written = newest is not None and (clock - newest) <= recent_seconds

    if running and recently_written:
        return AgentActivity(kind="working")
    if running:
        return AgentActivity(kind="waiting")
    return AgentActivity(kind="none")
