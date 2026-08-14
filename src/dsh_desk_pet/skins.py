"""First-party skin catalog. Default is whale. Switching a skin is identity-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skin:
    id: str
    name: str
    name_zh: str


SKINS: tuple[Skin, ...] = (
    Skin(id="whale", name="Whale", name_zh="鲸"),
    Skin(id="threadcore", name="Threadcore", name_zh="线核"),
    Skin(id="nautilus", name="Nautilus", name_zh="鹦鹉螺"),
    Skin(id="jellyfish", name="Jellyfish", name_zh="水母"),
)

DEFAULT_SKIN_ID = "whale"

_BY_ID = {skin.id: skin for skin in SKINS}


def list_skins() -> tuple[Skin, ...]:
    return SKINS


def default_skin() -> Skin:
    return _BY_ID[DEFAULT_SKIN_ID]


def get_skin(skin_id: str) -> Skin:
    try:
        return _BY_ID[skin_id]
    except KeyError as exc:
        raise KeyError(f"unknown skin: {skin_id}") from exc


def is_known_skin(skin_id: str) -> bool:
    return skin_id in _BY_ID
