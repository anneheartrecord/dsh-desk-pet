"""The skin catalog: four shipped skins, plus anything found on disk.

The catalog is not a hard-coded list, because a skin is really just a folder of
frames. Dropping `assets/skins/<id>/<state>/*.gif` in place is enough to make a
new one selectable — which is what lets a custom skin be generated from a photo
later without touching this file.

Directory scanning happens here rather than in `packs` to keep the import one
way: `packs` needs the catalog, so the catalog cannot need `packs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKIN_ROOT = Path(__file__).resolve().parents[2] / "assets" / "skins"


@dataclass(frozen=True)
class Skin:
    id: str
    name: str
    name_zh: str
    builtin: bool = True


BUILTIN_SKINS: tuple[Skin, ...] = (
    Skin(id="whale", name="Whale", name_zh="鲸"),
    Skin(id="threadcore", name="Threadcore", name_zh="线核"),
    Skin(id="nautilus", name="Nautilus", name_zh="鹦鹉螺"),
    Skin(id="jellyfish", name="Jellyfish", name_zh="水母"),
)

DEFAULT_SKIN_ID = "whale"

_BUILTIN_BY_ID = {skin.id: skin for skin in BUILTIN_SKINS}


def _title(skin_id: str) -> str:
    return skin_id.replace("-", " ").replace("_", " ").strip().title() or skin_id


def _discovered() -> tuple[Skin, ...]:
    """Skin folders on disk that are not part of the shipped set."""

    if not SKIN_ROOT.is_dir():
        return ()
    found = []
    for entry in sorted(SKIN_ROOT.iterdir()):
        if not entry.is_dir() or entry.name in _BUILTIN_BY_ID or entry.name.startswith("."):
            continue
        # A folder with no frames is a half-finished import, not a skin.
        if not any(entry.glob("*/*.gif")):
            continue
        name = _title(entry.name)
        found.append(Skin(id=entry.name, name=name, name_zh=name, builtin=False))
    return tuple(found)


def list_skins() -> tuple[Skin, ...]:
    """Every selectable skin, shipped ones first and in a stable order."""

    return BUILTIN_SKINS + _discovered()


def default_skin() -> Skin:
    return _BUILTIN_BY_ID[DEFAULT_SKIN_ID]


def get_skin(skin_id: str) -> Skin:
    for skin in list_skins():
        if skin.id == skin_id:
            return skin
    raise KeyError(f"unknown skin: {skin_id}")


def is_known_skin(skin_id: str) -> bool:
    return any(skin.id == skin_id for skin in list_skins())


# Kept as a module-level name because it reads well at call sites and several
# tests assert against the shipped set specifically.
SKINS = BUILTIN_SKINS
