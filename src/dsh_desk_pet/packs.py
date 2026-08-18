"""Shipped frame packs on disk.

`scripts/build_frames.py` writes two trees from one set of stills:

* ``assets/web/<skin>/<state>/NN.png`` — RGBA, used by *both* players now.
  The desktop pet draws through AppKit, which composites real alpha.
* ``assets/skins/<skin>/<state>/NN.gif`` — the same frames as a 1-bit matte.
  Kept because the pipeline and its gate are built around comparing the two,
  and because a GIF is the portable fallback if the pet is ever hosted by
  something that cannot take a PNG. Nothing shipped reads them at runtime.

A state with no art on disk falls back down `FALLBACK_STATE` rather than
rendering nothing, so a half-finished art pass degrades to a duller pet instead
of a blank window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import skins
from .anim import Timeline, auto_timeline

ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"
SKIN_ROOT = ASSET_ROOT / "skins"
WEB_ROOT = ASSET_ROOT / "web"
MANIFEST_PATH = SKIN_ROOT / "manifest.json"

# Every state the runtime can ask for, richest first in the fallback chain.
STATES = ("idle", "working", "waiting", "error", "happy", "sleeping")

# What to show when a state has no art yet. Chains until it reaches idle.
FALLBACK_STATE = {
    "happy": "idle",
    "sleeping": "idle",
    "working": "idle",
    "waiting": "idle",
    "error": "idle",
}

# A guard against half-written downloads, not a quality bar. Every real frame
# the build emits is tens of KB; anything this small is a truncated file, and
# loading one would fail to decode rather than just look wrong.
MIN_FRAME_BYTES = 400


@dataclass(frozen=True)
class FrameLoop:
    """The frames for one skin+state, plus the rhythm to play them at."""

    skin_id: str
    state: str
    resolved_state: str
    frames: tuple[Path, ...]
    timeline: Timeline

    @property
    def is_fallback(self) -> bool:
        return self.resolved_state != self.state

    def frame_at(self, elapsed_ms: int) -> Path | None:
        if not self.frames:
            return None
        return self.frames[self.timeline.frame_at(elapsed_ms) % len(self.frames)]


def _user_manifest(skin_id: str) -> dict:
    """A user-made skin carries its own manifest; the shipped one is packaged."""

    path = skins.user_frame_root() / skin_id / "manifest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"frame_size": 200, "skins": {}}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def frame_size() -> int:
    return int(manifest().get("frame_size", 200))


def _frames_in(directory: Path, suffix: str) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(p for p in directory.glob(f"*{suffix}") if p.is_file() and p.stat().st_size > MIN_FRAME_BYTES)
    )


def skin_dir(skin_id: str, *, web: bool = False) -> Path:
    """Where this skin's frames live.

    A user-made skin is installed outside the package, because the installed
    copy sits in node_modules and is replaced wholesale on upgrade. The package
    tree wins, so a stray user folder cannot shadow a shipped skin.
    """

    root = WEB_ROOT if web else SKIN_ROOT
    shipped = root / skin_id
    if shipped.is_dir():
        return shipped
    user = skins.user_frame_root() / skin_id
    if web and user.is_dir():
        return user
    return shipped


def frames_for(skin_id: str, state: str, *, web: bool = False) -> tuple[Path, ...]:
    return _frames_in(skin_dir(skin_id, web=web) / state, ".png" if web else ".gif")


def resolve_state(skin_id: str, state: str, *, web: bool = False) -> tuple[str, tuple[Path, ...]]:
    """Walk the fallback chain until a state has art, or give up on empty."""

    seen: set[str] = set()
    current = state
    while current and current not in seen:
        seen.add(current)
        found = frames_for(skin_id, current, web=web)
        if found:
            return current, found
        current = FALLBACK_STATE.get(current, "")
    return state, ()


def _declared_timeline(skin_id: str, state: str) -> Timeline | None:
    """Honour a hand-tuned `timeline` in the manifest over the generated one."""

    raw = (_skin_manifest(skin_id).get("timelines") or {}).get(state)
    if not raw:
        return None
    try:
        steps = tuple((int(index), int(ms)) for index, ms in raw)
    except (TypeError, ValueError):
        # A user-made skin's manifest is a file we did not write. A malformed
        # timeline must fall back to the generated rhythm, not raise on the
        # render path — an exception there unwinds into an ObjC callback.
        return None
    return Timeline(steps) if steps else None


@lru_cache(maxsize=128)
def _loop_cached(skin_id: str, state: str, web: bool) -> FrameLoop:
    resolved, frames = resolve_state(skin_id, state, web=web)
    timeline = _declared_timeline(skin_id, resolved) or auto_timeline(resolved, len(frames))
    return FrameLoop(
        skin_id=skin_id,
        state=state,
        resolved_state=resolved,
        frames=frames,
        timeline=timeline,
    )


def loop_for(skin_id: str, state: str, *, web: bool = False) -> FrameLoop:
    """Frames plus rhythm for a skin+state.

    Cached: the renderer calls this thirty times a second, and uncached it does
    a `glob` plus a `stat` per file on every frame — a directory scan at 30Hz
    for a directory that only changes when someone reruns the build script.

    An empty result is the one case worth a second look. `skins` discovers skin
    folders from disk on every call, so a skin generated while the pet is
    running becomes selectable immediately — and would then be served a cached
    empty loop and freeze the sprite on its last frame. Missing art is rare and
    a single extra directory scan is cheap, so an empty hit re-checks disk.
    """

    loop = _loop_cached(skin_id, state, web)
    if not loop.frames and skin_dir(skin_id, web=web).is_dir():
        # Checked against the tree the frames actually come from. This tested
        # the GIF tree before, so a skin with PNG frames only — which is every
        # skin a user installs — never satisfied it and kept its cached empty
        # loop, freezing the sprite on its last frame.
        reset_cache()
        loop = _loop_cached(skin_id, state, web)
    return loop


def reset_cache() -> None:
    """Forget the manifest and every loaded loop. Call after rebuilding art."""

    manifest.cache_clear()
    _loop_cached.cache_clear()


def frame_at(skin_id: str, state: str, elapsed_ms: int, *, web: bool = False) -> Path | None:
    return loop_for(skin_id, state, web=web).frame_at(elapsed_ms)


def pack_inventory(*, web: bool = False) -> dict[str, dict[str, int]]:
    """skin -> state -> frame count, counting only art that really exists."""

    root = WEB_ROOT if web else SKIN_ROOT
    skins = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return {
        skin: {state: len(frames_for(skin, state, web=web)) for state in STATES}
        for skin in skins
    }


def _skin_manifest(skin_id: str) -> dict:
    entry = manifest().get("skins", {}).get(skin_id)
    if entry:
        return entry
    return _user_manifest(skin_id)


def subject_box(skin_id: str) -> tuple[int, int, int, int] | None:
    """Where the character sits inside its padded frame, in frame pixels.

    Recorded by the build. The window uses it for hit testing, so a click on an
    empty corner falls through to whatever is behind the pet instead of being
    swallowed by the window rectangle.
    """

    box = _skin_manifest(skin_id).get("subject_box")
    if not box or len(box) != 4:
        return None
    try:
        return tuple(int(v) for v in box)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def available_skins() -> tuple[str, ...]:
    if not SKIN_ROOT.is_dir():
        return ()
    return tuple(sorted(p.name for p in SKIN_ROOT.iterdir() if p.is_dir()))
