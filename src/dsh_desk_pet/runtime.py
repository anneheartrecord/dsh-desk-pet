"""PetRuntime — the state machine the window, the web route and the tests share.

The observer only ever reports what the agent is doing. Everything that makes
the pet feel like it has a mood of its own lives here instead:

* `happy` is a one-shot. A finished run earns a celebration, then decays back
  to idle on a timer rather than sticking as a sixth resting state.
* `sleeping` is reached by *nothing happening*, which no activity label can
  express. Long idle dozes off; any activity or any poke wakes it.
* `do_not_disturb` looks the same on screen and behaves the opposite way: the
  user asked for quiet, so no observation, timer or poke may take it away. Only
  the user gives it back. It is not persisted.
* A poke (click) queues a hop the renderer draws on top of the current loop.

The clock is always passed in. Nothing here calls `time.time()`, so a test can
drive five minutes of behaviour in a loop with no sleeping.
"""

from __future__ import annotations

from .mapper import AgentActivity, PetState, map_activity
from .skins import DEFAULT_SKIN_ID, get_skin, is_known_skin

# How long the celebration holds before falling back to idle.
HAPPY_MS = 3200
# Nothing to do *and* nobody at the keyboard for this long, and the pet dozes.
# Short, because it is gated on the pointer having stopped moving as well —
# without that gate this had to be minutes, and a quiet agent was
# indistinguishable from a user who had walked away.
SLEEP_AFTER_MS = 90 * 1000
# Length of the bounce a click queues up.
HOP_MS = 520


class PetRuntime:
    """Current skin, current state, and the timers that move between states."""

    def __init__(self, skin_id: str = DEFAULT_SKIN_ID, state: PetState = "idle", now_ms: int = 0) -> None:
        self._skin_id = get_skin(skin_id).id
        self._state: PetState = state
        self._state_since_ms = now_ms
        self._hop_until_ms = 0
        self._do_not_disturb = False

    @property
    def skin_id(self) -> str:
        return self._skin_id

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def hop_until_ms(self) -> int:
        return self._hop_until_ms

    @property
    def do_not_disturb(self) -> bool:
        return self._do_not_disturb

    def set_do_not_disturb(self, on: bool, now_ms: int) -> PetState:
        """Turn the user's quiet mode on or off.

        Deliberately not persisted. It is a mode you choose for the next few
        minutes, and a pet that came back silent after a restart would read as
        a hung process rather than a setting.

        Turning it on shows the sleeping pose, so it looks like what it is.

        Turning it off wakes the pet to idle and re-arms the doze timer. Leaving
        the pose alone would be defensible — the next observation would resume
        it — but an idle observation refuses to lift `sleeping`, and `tick` has
        no exit from it, so a pet whose agent had nothing to do would stay
        visibly asleep with the menu item now reading unchecked. That is the one
        confusion this mode is most likely to cause, since it looks identical to
        the natural doze.
        """

        was_on = self._do_not_disturb
        self._do_not_disturb = bool(on)
        if self._do_not_disturb:
            return self._enter("sleeping", now_ms)
        if was_on:
            return self._enter("idle", now_ms)
        return self._state

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

        if self._do_not_disturb:
            # The whole point of the mode: the agent keeps working and the
            # observer keeps reporting, but none of it reaches the screen.
            return self._state
        observed = map_activity(activity)
        if observed == "idle" and self._state in ("sleeping", "happy"):
            # Let the timers in `tick` own these two; a stream of idle polls
            # must not keep resetting the doze countdown or cut a celebration.
            return self._state
        return self._enter(observed, now_ms)

    def tick(self, now_ms: int, user_idle_ms: int | None = None) -> PetState:
        """Advance the self-driven transitions. Safe to call every frame.

        ``user_idle_ms`` is how long the pointer has sat still. Dozing needs
        both clocks: an agent with nothing to do is not the same thing as a
        desk with nobody at it, and only the second one should put the pet to
        sleep. Pass ``None`` when there is no pointer to watch and the state
        clock decides alone.
        """

        if self._do_not_disturb:
            return self._state
        elapsed = self.state_elapsed_ms(now_ms)
        if self._state == "happy" and elapsed >= HAPPY_MS:
            return self._enter("idle", now_ms)
        if self._state == "idle" and elapsed >= SLEEP_AFTER_MS:
            if user_idle_ms is None or user_idle_ms >= SLEEP_AFTER_MS:
                return self._enter("sleeping", now_ms)
        return self._state

    def poke(self, now_ms: int) -> PetState:
        """User touched the pet: wake it up and queue a bounce.

        Under do-not-disturb the bounce still happens but the waking does not.
        Petting a sleeping pet should feel alive, and it should not quietly
        cancel a mode the user set from the menu — only the menu gives it back.
        """

        self._hop_until_ms = now_ms + HOP_MS
        if self._do_not_disturb:
            return self._state
        if self._state == "sleeping":
            return self._enter("idle", now_ms)
        return self._state

    def set_skin(self, skin_id: str) -> PetState:
        """Switch skin. Returns the (unchanged) current state."""

        if not is_known_skin(skin_id):
            raise KeyError(f"unknown skin: {skin_id}")
        self._skin_id = skin_id
        return self._state
