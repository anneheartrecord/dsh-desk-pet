"""Shipped frame packs on disk.

`scripts/build_frames.py` writes two trees from one set of stills:

* ``assets/skins/<skin>/<state>/NN.gif`` — what the desktop window blits.
  macOS ships Tk 8.5, whose ``PhotoImage`` reads GIF only, so GIF is not a
  legacy choice here, it is the only one.
* ``assets/web/<skin>/<state>/NN.png`` — RGBA for the in-page overlay, which
  runs in a browser and would rather have real alpha than a 1-bit matte.

A state with no art on disk falls back down `FALLBACK_STATE` rather than
rendering nothing, so a half-finished art pass degrades to a duller pet instead
of a blank window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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
# loading one would crash Tk's GIF reader rather than just look wrong.
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


def frames_for(skin_id: str, state: str, *, web: bool = False) -> tuple[Path, ...]:
    root = WEB_ROOT if web else SKIN_ROOT
    return _frames_in(root / skin_id / state, ".png" if web else ".gif")


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

    entry = manifest().get("skins", {}).get(skin_id, {})
    raw = (entry.get("timelines") or {}).get(state)
    if not raw:
        return None
    steps = tuple((int(index), int(ms)) for index, ms in raw)
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
    """

    return _loop_cached(skin_id, state, web)


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


def available_skins() -> tuple[str, ...]:
    if not SKIN_ROOT.is_dir():
        return ()
    return tuple(sorted(p.name for p in SKIN_ROOT.iterdir() if p.is_dir()))
