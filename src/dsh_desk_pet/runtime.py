"""PetRuntime — the state machine the window, the web route and the tests share.

The observer only ever reports what the agent is doing. Everything that makes
the pet feel like it has a mood of its own lives here instead:

* `happy` is a one-shot. A finished run earns a celebration, then decays back
  to idle on a timer rather than sticking as a sixth resting state.
* `sleeping` is reached by *nothing happening*, which no activity label can
  express. Long idle dozes off; any activity or any poke wakes it.
* A poke (click) queues a hop the renderer draws on top of the current loop.

The clock is always passed in. Nothing here calls `time.time()`, so a test can
drive five minutes of behaviour in a loop with no sleeping.
"""

from __future__ import annotations

from .mapper import AgentActivity, PetState, map_activity
from .skins import DEFAULT_SKIN_ID, get_skin, is_known_skin

# How long the celebration holds before falling back to idle.
HAPPY_MS = 3200
# Idle this long with nothing to do and the pet dozes off.
SLEEP_AFTER_MS = 5 * 60 * 1000
# Length of the bounce a click queues up.
HOP_MS = 520


class PetRuntime:
    """Current skin, current state, and the timers that move between states."""

    def __init__(self, skin_id: str = DEFAULT_SKIN_ID, state: PetState = "idle", now_ms: int = 0) -> None:
        self._skin_id = get_skin(skin_id).id
        self._state: PetState = state
        self._state_since_ms = now_ms
        self._hop_until_ms = 0

    @property
    def skin_id(self) -> str:
        return self._skin_id

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def hop_until_ms(self) -> int:
        return self._hop_until_ms

    def state_elapsed_ms(self, now_ms: int) -> int:
        """Time in the current state — this is what drives the frame timeline."""

        return max(0, now_ms - self._state_since_ms)

    def _enter(self, state: PetState, now_ms: int) -> PetState:
        if state != self._state:
            self._state = state
            self._state_since_ms = now_ms
        return self._state

    def apply_activity(self, activity: AgentActivity | None, now_ms: int = 0) -> PetState:
        """Take an observation. Idle observations never disturb a live nap."""

        observed = map_activity(activity)
        if observed == "idle" and self._state in ("sleeping", "happy"):
            # Let the timers in `tick` own these two; a stream of idle polls
            # must not keep resetting the doze countdown or cut a celebration.
            return self._state
        return self._enter(observed, now_ms)

    def tick(self, now_ms: int) -> PetState:
        """Advance the self-driven transitions. Safe to call every frame."""

        elapsed = self.state_elapsed_ms(now_ms)
        if self._state == "happy" and elapsed >= HAPPY_MS:
            return self._enter("idle", now_ms)
        if self._state == "idle" and elapsed >= SLEEP_AFTER_MS:
            return self._enter("sleeping", now_ms)
        return self._state

    def poke(self, now_ms: int) -> PetState:
        """User touched the pet: wake it up and queue a bounce."""

        self._hop_until_ms = now_ms + HOP_MS
        if self._state == "sleeping":
            return self._enter("idle", now_ms)
        return self._state

    def set_skin(self, skin_id: str) -> PetState:
        """Switch skin. Returns the (unchanged) current state."""

        if not is_known_skin(skin_id):
            raise KeyError(f"unknown skin: {skin_id}")
        self._skin_id = skin_id
        return self._state
