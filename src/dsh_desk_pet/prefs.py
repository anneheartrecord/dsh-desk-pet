"""Small persisted preferences: where the pet sits, how big it is, which skin.

Separate from `bridge`, which publishes *live* state for the page overlay to
read. This is the other direction — things the user set that must survive a
restart. Dragging the pet somewhere and having it jump back to the top-left
every time `dsh web` restarts is the kind of detail that makes a desk pet feel
like a debug window instead of a pet.

Reads never raise. A corrupt or absent file yields defaults, because the pet
failing to start over a preferences file would be a far worse bug than the pet
forgetting where it was.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .skins import DEFAULT_SKIN_ID, is_known_skin

PREFS_DIRNAME = ".dsh-desk-pet"
PREFS_FILENAME = "prefs.json"

MIN_SCALE = 0.5
MAX_SCALE = 2.0


@dataclass
class Prefs:
    skin_id: str = DEFAULT_SKIN_ID
    x: int | None = None
    y: int | None = None
    scale: float = 1.0

    def clamped(self) -> "Prefs":
        """Repair anything a hand-edited or stale file could get wrong."""

        skin = self.skin_id if is_known_skin(self.skin_id) else DEFAULT_SKIN_ID
        try:
            scale = float(self.scale)
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        x = self.x if isinstance(self.x, int) else None
        y = self.y if isinstance(self.y, int) else None
        # A window parked at a negative offset can land fully off-screen with no
        # way to drag it back, so treat those as "no saved position".
        if x is not None and x < 0:
            x = None
        if y is not None and y < 0:
            y = None
        return Prefs(skin_id=skin, x=x, y=y, scale=scale)


def prefs_path(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / PREFS_DIRNAME / PREFS_FILENAME


def load(home: Path | None = None) -> Prefs:
    try:
        payload = json.loads(prefs_path(home).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Prefs()
    if not isinstance(payload, dict):
        return Prefs()
    known = {field: payload.get(field) for field in Prefs().__dict__ if field in payload}
    try:
        return Prefs(**known).clamped()
    except TypeError:
        return Prefs()


def save(prefs: Prefs, home: Path | None = None) -> bool:
    """Best-effort persist. Returns False rather than raising on a bad home."""

    path = prefs_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".prefs-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(prefs.clamped()), handle, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True
