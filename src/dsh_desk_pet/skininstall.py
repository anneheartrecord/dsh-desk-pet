"""Install a generated skin without ever damaging one that already works.

Three rules shape this, each of them written against a specific way it could
go wrong.

**Stage, then rename.** The staging directory is a dot-prefixed sibling inside
the skin root, so the rename stays on one filesystem and no reader ever sees a
half-written skin.

**The id is checked against an allowlist, and containment is proved before
anything is deleted.** Replacing a skin means removing the old directory
recursively, and a blocklist lets through forms that are still unsafe: an empty
id resolves back to the skin root itself and would point that delete at every
skin the user has.

**A directory we did not write is never touched.** The marker file is what
tells our own install apart from a folder the user placed by hand, and without
one we refuse rather than overwrite.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import imaging, skins

MARKER = ".installed-by-dsh-desk-pet.json"
MANIFEST = "manifest.json"
FORMAT = 1
STATES = ("idle", "working", "waiting", "error", "happy", "sleeping")
FRAMES_PER_STATE = 3

# Lowercase, digits, dash and underscore, starting on an alphanumeric. Anything
# outside this is refused rather than sanitised, so there is no transformation
# that could turn one valid id into another.
VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# A frame that keyed to almost nothing is a failure. So is one that keyed to
# almost everything: if the plate was never removed the frame is ~100% opaque,
# which passes a floor more easily than good art does.
MIN_COVERAGE = 0.05
MAX_COVERAGE = 0.85
# Border-unreachable transparent regions are holes punched through the
# character. A few pixels are antialiasing; a large one is a face with its eyes
# cut out.
MAX_HOLE_PX = 400
MAX_LABEL = 120


class InstallError(ValueError):
    """Refused, with a reason the user can act on."""


def _root(home: Path | None = None) -> Path:
    return skins.user_frame_root(home)


def validate_id(skin_id: str) -> str:
    if not isinstance(skin_id, str) or not VALID_ID.match(skin_id):
        raise InstallError(
            f"skin id {skin_id!r} must be 1-32 characters of a-z, 0-9, dash or underscore, "
            "starting with a letter or digit")
    # Case-insensitively, because the default macOS filesystem is: 'DeepSeek'
    # and 'deepseek' would be the same directory.
    lowered = skin_id.lower()
    for builtin in skins.BUILTIN_SKINS:
        if builtin.id.lower() == lowered:
            raise InstallError(f"{skin_id!r} is a built-in skin")
    return skin_id


def _target(skin_id: str, home: Path | None = None) -> Path:
    """The install path, proved to sit inside the skin root."""

    root = _root(home).resolve()
    target = (root / skin_id).resolve()
    if target == root or root not in target.parents:
        raise InstallError(f"refusing a target outside the skin root: {target}")
    return target


def inspect_frames(source: Path) -> dict:
    """Decode every frame and measure it. Raises on the first refusal."""

    boxes = []
    for state in STATES:
        directory = source / state
        frames = sorted(p for p in directory.glob("*.png")) if directory.is_dir() else []
        if len(frames) < FRAMES_PER_STATE:
            raise InstallError(
                f"state {state!r} has {len(frames)} frames; {FRAMES_PER_STATE} are required")
        for frame in frames[:FRAMES_PER_STATE]:
            try:
                w, h, raw = imaging.decode_png(frame.read_bytes())
            except imaging.ImageError as exc:
                raise InstallError(f"{state}/{frame.name}: {exc}") from exc
            box, coverage = imaging.alpha_bounds(raw, w, h)
            if coverage < MIN_COVERAGE:
                raise InstallError(
                    f"{state}/{frame.name} is {coverage:.0%} opaque; the character is missing")
            if coverage > MAX_COVERAGE:
                raise InstallError(
                    f"{state}/{frame.name} is {coverage:.0%} opaque, so its background was "
                    "never removed — generate it on a flat magenta plate")
            holes = _interior_holes(raw, w, h)
            if holes > MAX_HOLE_PX:
                raise InstallError(
                    f"{state}/{frame.name} has {holes}px of holes punched through the character")
            if box is not None:
                boxes.append((box, w, h))
    if not boxes:
        raise InstallError("no frame produced a usable subject box")
    return {"subject_box": _union_box(boxes)}


def _interior_holes(raw: bytearray, w: int, h: int) -> int:
    """Transparent pixels that cannot be reached from the border."""

    from collections import deque

    seen = bytearray(w * h)
    queue: deque = deque()
    for x in range(w):
        for y in (0, h - 1):
            queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        index = y * w + x
        if seen[index] or raw[index * 4 + 3] >= imaging.ALPHA_CUTOFF:
            continue
        seen[index] = 1
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return sum(
        1 for i in range(w * h)
        if not seen[i] and raw[i * 4 + 3] < imaging.ALPHA_CUTOFF
    )


def _union_box(boxes) -> list[int]:
    """The subject box, in final-frame pixels.

    Without it `is_on_pet` returns true across the whole rectangle and the skin
    swallows clicks on its empty corners.
    """

    x0 = min(b[0] for b, _, _ in boxes)
    y0 = min(b[1] for b, _, _ in boxes)
    x1 = max(b[2] for b, _, _ in boxes)
    y1 = max(b[3] for b, _, _ in boxes)
    size = imaging.FRAME_SIZE
    return [int(x0 * size), int(y0 * size),
            min(size - 1, int(x1 * size)), min(size - 1, int(y1 * size))]


def read_marker(path: Path) -> dict | None:
    marker = path / MARKER
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def install(source: Path, skin_id: str, *, home: Path | None = None,
            generator: str = "", now=None) -> Path:
    """Install `source` as `skin_id`. Returns the installed path."""

    validate_id(skin_id)
    source = Path(source).resolve()
    root = _root(home)
    root.mkdir(parents=True, exist_ok=True)
    if root.resolve() == source or root.resolve() in source.parents:
        raise InstallError("the frames must come from outside the skin root")

    target = _target(skin_id, home)
    if target.exists():
        if not target.is_dir() or target.is_symlink():
            raise InstallError(f"{target} is not a directory we can replace")
        if read_marker(target) is None:
            raise InstallError(
                f"{skin_id!r} was placed there by hand, not installed by us; refusing to replace it")

    measured = inspect_frames(source)

    staging = root / f".{skin_id}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        shutil.copytree(source, staging)
        (staging / MANIFEST).write_text(
            json.dumps({
                "frame_size": imaging.FRAME_SIZE,
                "format": FORMAT,
                "subject_box": measured["subject_box"],
            }, indent=2, sort_keys=True),
            encoding="utf-8")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))
        (staging / MARKER).write_text(
            json.dumps({
                "format": FORMAT,
                "installed_at": stamp,
                "frames": FRAMES_PER_STATE * len(STATES),
                # Free text, truncated. Never a command line, environment or
                # URL: a skin is a directory a user will zip and send, and the
                # marker travels with it.
                "generator": str(generator)[:MAX_LABEL],
            }, indent=2, sort_keys=True),
            encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except InstallError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallError(f"could not install {skin_id!r}: {exc}") from exc
    return target


def is_supported(path: Path) -> bool:
    """Is this skin's layout one this version understands?"""

    marker = read_marker(path)
    if marker is None:
        return True  # hand-placed; not ours to version
    try:
        return int(marker.get("format", FORMAT)) <= FORMAT
    except (TypeError, ValueError):
        return False
