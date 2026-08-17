"""Read the local DSH session list, for the panel the pet opens when clicked.

Everything here comes off the filesystem, because that is all there is: DSH has
no local API to ask. What the layout gives away for free turns out to be most of
what a session list needs:

    ~/.dsh/sessions/<cwd with separators escaped>/session-<uuid>/session.jsonl.zstd

The directory name *is* the working directory, so the project is known without
opening anything. The file's mtime is when the session last did something. Only
the human-readable title lives inside the log, and the log is zstd — which
Python 3.9 cannot decompress and which macOS does not ship a decompressor for.
So the title is an enhancement: taken from the log when a `zstd` binary happens
to be around, and otherwise the project's folder name, which is what a person
would have called it anyway.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# Session activity newer than this reads as "happening now".
ACTIVE_SECONDS = 20.0
# How much of the decompressed log to scan for a title. Titles are set early.
TITLE_SCAN_BYTES = 256 * 1024
MAX_TITLE_CHARS = 28


@dataclass(frozen=True)
class Session:
    """One DSH session, as much as the filesystem will admit to."""

    session_id: str
    cwd: Path
    title: str
    last_active: float
    active: bool

    @property
    def project(self) -> str:
        return self.cwd.name or str(self.cwd)

    def age_label(self, now: float | None = None) -> str:
        """Relative time, in the shape the panel wants to print."""

        seconds = max(0.0, (time.time() if now is None else now) - self.last_active)
        if seconds < 10:
            return "just now"
        if seconds < 90:
            return f"{int(seconds)}s ago"
        if seconds < 90 * 60:
            return f"{int(seconds // 60)}m ago"
        if seconds < 36 * 3600:
            return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"


def default_sessions_root(home: Path | None = None) -> Path:
    base = home if home is not None else Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    return base / "sessions"


def decode_cwd(directory_name: str) -> Path:
    """Turn `--Users-abc-my-project--` back into `/Users/abc/my-project`.

    Ambiguous on its own: DSH escapes path separators as dashes, so a folder
    whose name contains a dash is indistinguishable from a separator, and
    `deepseek-harness` naively decodes to `deepseek/harness`. The filesystem
    settles it — at each step, if joining the next segment with a dash names
    something that exists, that is what it was. Falls back to treating every
    dash as a separator when nothing on disk matches, which is the best guess
    available for a project that has since been moved or deleted.
    """

    trimmed = directory_name.strip("-")
    if not trimmed:
        return Path("/")

    segments = trimmed.split("-")
    path = Path("/")
    index = 0
    while index < len(segments):
        candidate = path / segments[index]
        step = index + 1
        # Prefer the longest dash-joined name that exists.
        while step < len(segments):
            joined = Path(str(candidate) + "-" + segments[step])
            if joined.exists():
                candidate = joined
                step += 1
                continue
            break
        if not candidate.exists() and not path.joinpath(segments[index]).exists():
            # Nothing here resolves; treat the remainder as plain separators.
            return Path("/" + "/".join(segments))
        path = candidate
        index = step
    return path


def _zstd_binary() -> str | None:
    return shutil.which("zstd") or shutil.which("unzstd")


def _title_from_log(log: Path) -> str | None:
    """Pull `session/title` out of the log, if anything here can read it."""

    binary = _zstd_binary()
    if binary is None or not log.is_file():
        return None
    try:
        proc = subprocess.run(
            [binary, "-dc", str(log)], capture_output=True, timeout=4, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None

    title = None
    for line in proc.stdout[:TITLE_SCAN_BYTES].decode("utf-8", "replace").splitlines():
        if '"session/title"' not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = payload.get("data") or {}
        candidate = data.get("title") or data.get("text")
        if isinstance(candidate, str) and candidate.strip():
            title = candidate.strip()
    return title


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_TITLE_CHARS:
        return text
    return text[: MAX_TITLE_CHARS - 1] + "…"


def list_sessions(
    home: Path | None = None, *, limit: int = 6, now: float | None = None, titles: bool = True
) -> list[Session]:
    """Most recently active sessions first.

    ``titles=False`` skips the subprocess per session — the panel uses it for a
    first paint, so clicking the pet feels instant even with a lot of history.
    """

    root = default_sessions_root(home)
    if not root.is_dir():
        return []

    clock = time.time() if now is None else now
    found: list[Session] = []
    try:
        project_dirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return []

    for project in project_dirs:
        try:
            session_dirs = [p for p in project.iterdir() if p.is_dir()]
        except OSError:
            continue
        for session in session_dirs:
            log = session / "session.jsonl.zstd"
            try:
                stamp = (log if log.is_file() else session).stat().st_mtime
            except OSError:
                continue
            cwd = decode_cwd(project.name)
            found.append(
                Session(
                    session_id=session.name,
                    cwd=cwd,
                    title=cwd.name or session.name,
                    last_active=stamp,
                    active=(clock - stamp) <= ACTIVE_SECONDS,
                )
            )

    found.sort(key=lambda s: s.last_active, reverse=True)
    shown = found[:limit]

    if titles:
        # Only for the rows actually on screen: decompressing every session's
        # log to label six lines would make the panel cost grow with history.
        resolved = []
        for session in shown:
            log = default_sessions_root(home) / _project_dirname(session) / session.session_id / "session.jsonl.zstd"
            title = _title_from_log(log) or session.title
            resolved.append(
                Session(
                    session_id=session.session_id,
                    cwd=session.cwd,
                    title=_shorten(title),
                    last_active=session.last_active,
                    active=session.active,
                )
            )
        shown = resolved
    else:
        shown = [
            Session(s.session_id, s.cwd, _shorten(s.title), s.last_active, s.active) for s in shown
        ]

    return shown


def _project_dirname(session: Session) -> str:
    """Re-encode a cwd the way DSH names its session folders."""

    return "--" + str(session.cwd).strip("/").replace("/", "-") + "--"


def total_count(home: Path | None = None) -> int:
    root = default_sessions_root(home)
    if not root.is_dir():
        return 0
    count = 0
    try:
        for project in root.iterdir():
            if not project.is_dir():
                continue
            count += sum(1 for p in project.iterdir() if p.is_dir())
    except OSError:
        return count
    return count
