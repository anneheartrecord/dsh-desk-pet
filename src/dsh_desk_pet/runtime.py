"""PetRuntime is the API the window and tests share."""

from __future__ import annotations

from .mapper import AgentActivity, PetState, map_activity
from .skins import DEFAULT_SKIN_ID, get_skin, is_known_skin


class PetRuntime:
    """Holds current display state and selected skin.

    ``set_skin`` is what the desktop picker calls. It never remaps state.
    """

    def __init__(self, skin_id: str = DEFAULT_SKIN_ID, state: PetState = "idle") -> None:
        self._skin_id = get_skin(skin_id).id
        self._state: PetState = state

    @property
    def skin_id(self) -> str:
        return self._skin_id

    @property
    def state(self) -> PetState:
        return self._state

    def apply_activity(self, activity: AgentActivity | None) -> PetState:
        self._state = map_activity(activity)
        return self._state

    def set_skin(self, skin_id: str) -> PetState:
        """Switch skin. Returns the (unchanged) current state."""

        if not is_known_skin(skin_id):
            raise KeyError(f"unknown skin: {skin_id}")
        self._skin_id = skin_id
        return self._state
