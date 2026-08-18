"""The skin catalog: the shipped skins, plus anything found on disk.

The catalog is not a hard-coded list, because a skin is really just a folder of
frames. Dropping `assets/web/<id>/<state>/*.png` in place is enough to make a
new one selectable — which is what lets a custom skin be generated from a photo
later without touching this file.

Directory scanning happens here rather than in `packs` to keep the import one
way: `packs` needs the catalog, so the catalog cannot need `packs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Discovery looks at the PNG tree, because that is the one the renderer plays:
# every call site passes web=True. Gating on `assets/skins/*/*.gif` instead
# meant a skin was only discoverable if it also carried frames in the format the
# dead Tk path used — so a hand-added skin was invisible, and once the GIFs
# stopped shipping there was nothing to find at all.
FRAME_ROOT = Path(__file__).resolve().parents[2] / "assets" / "web"
# Where a skin the user made lives. Deliberately outside the package: the
# installed copy sits in node_modules and is replaced wholesale on upgrade, so
# a skin written there would not survive one. Prefs and state already live in
# this directory.
USER_ROOT_NAME = ".dsh-desk-pet"


def user_frame_root(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / USER_ROOT_NAME / "skins"
# Kept for the manifest's sake; not what decides whether a skin exists.
SKIN_ROOT = Path(__file__).resolve().parents[2] / "assets" / "skins"


@dataclass(frozen=True)
class Skin:
    id: str
    name: str
    name_zh: str
    builtin: bool = True


BUILTIN_SKINS: tuple[Skin, ...] = (
    # The default is the DeepSeek whale, because this is a DSH plugin and the
    # pet on your desk should be the one you already recognise.
    Skin(id="deepseek", name="DeepSeek Whale", name_zh="深索鲸"),
    Skin(id="bluewhale", name="Blue Whale", name_zh="蓝鲸"),
    Skin(id="threadcore", name="Threadcore", name_zh="线核"),
    Skin(id="nautilus", name="Nautilus", name_zh="鹦鹉螺"),
    Skin(id="jellyfish", name="Jellyfish", name_zh="水母"),
)

DEFAULT_SKIN_ID = "deepseek"

_BUILTIN_BY_ID = {skin.id: skin for skin in BUILTIN_SKINS}


def _title(skin_id: str) -> str:
    return skin_id.replace("-", " ").replace("_", " ").strip().title() or skin_id


def _readable_format(path: Path) -> bool:
    """Is this skin's layout one this version understands?

    Imported lazily: `skininstall` imports this module, so a module-level
    import would be circular.
    """

    try:
        from .skininstall import is_supported
    except ImportError:  # pragma: no cover - defensive
        return True
    try:
        return is_supported(path)
    except Exception:  # pragma: no cover - never block discovery on this
        return True


def _discovered(home: Path | None = None) -> tuple[Skin, ...]:
    """Skin folders on disk that are not part of the shipped set.

    Two roots are searched: the package's own tree, for a skin dropped in by a
    developer, and the user directory, where anything generated is installed. A
    builtin id is never shadowed, so a stray folder cannot replace a shipped
    skin.
    """

    found = []
    seen = set(_BUILTIN_BY_ID)
    for root in (FRAME_ROOT, user_frame_root(home)):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name in seen or entry.name.startswith("."):
                continue
            # A folder with no frames is a half-finished import, not a skin.
            if not any(entry.glob("*/*.png")):
                continue
            if not _readable_format(entry):
                # Written by a newer version than this one. Skipped rather than
                # loaded or deleted: the user paid to generate it, and a later
                # release can migrate it.
                continue
            seen.add(entry.name)
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
