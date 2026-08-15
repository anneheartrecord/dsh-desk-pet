"""The self-driven half of the state machine: celebration decay, dozing, pokes.

Every test drives an explicit clock. Nothing here sleeps, so five minutes of
idle behaviour is asserted in microseconds.
"""

from __future__ import annotations

import unittest

from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.runtime import HAPPY_MS, SLEEP_AFTER_MS, PetRuntime


class DefaultsTests(unittest.TestCase):
    def test_starts_on_whale_idle(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.skin_id, "whale")
        self.assertEqual(runtime.state, "idle")

    def test_unknown_skin_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            PetRuntime().set_skin("dragon")

    def test_set_skin_does_not_change_state(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="running"), now_ms=0)
        self.assertEqual(runtime.set_skin("nautilus"), "working")
        self.assertEqual(runtime.state, "working")


class ActivityTests(unittest.TestCase):
    def test_activity_maps_onto_states(self) -> None:
        runtime = PetRuntime()
        for kind, expected in (
            ("running", "working"),
            ("blocked", "waiting"),
            ("failed", "error"),
            ("none", "idle"),
        ):
            runtime.apply_activity(AgentActivity(kind=kind), now_ms=0)
            self.assertEqual(runtime.state, expected, kind)

    def test_completion_celebrates_before_settling(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="completed"), now_ms=1_000)
        self.assertEqual(runtime.state, "happy")

    def test_state_elapsed_resets_on_transition(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="running"), now_ms=5_000)
        self.assertEqual(runtime.state_elapsed_ms(5_400), 400)


class DecayTests(unittest.TestCase):
    def test_happy_falls_back_to_idle_on_its_own(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="done"), now_ms=0)
        self.assertEqual(runtime.tick(HAPPY_MS - 1), "happy")
        self.assertEqual(runtime.tick(HAPPY_MS), "idle")

    def test_idle_polls_do_not_cut_the_celebration_short(self) -> None:
        """`dsh` reports idle the instant a run ends — that must not kill `happy`."""

        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="completed"), now_ms=0)
        runtime.apply_activity(AgentActivity(kind="none"), now_ms=500)
        self.assertEqual(runtime.state, "happy")

    def test_long_idle_dozes_off(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS - 1), "idle")
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS), "sleeping")

    def test_idle_polls_do_not_reset_the_doze_countdown(self) -> None:
        runtime = PetRuntime()
        for t in range(0, SLEEP_AFTER_MS, 30_000):
            runtime.apply_activity(AgentActivity(kind="none"), now_ms=t)
            runtime.tick(t)
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS), "sleeping")

    def test_work_wakes_a_sleeping_pet(self) -> None:
        runtime = PetRuntime()
        runtime.tick(SLEEP_AFTER_MS)
        self.assertEqual(runtime.state, "sleeping")
        runtime.apply_activity(AgentActivity(kind="running"), now_ms=SLEEP_AFTER_MS + 10)
        self.assertEqual(runtime.state, "working")

    def test_sleeping_does_not_immediately_re_enter(self) -> None:
        runtime = PetRuntime()
        runtime.tick(SLEEP_AFTER_MS)
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS + 1), "sleeping")


class PresenceTests(unittest.TestCase):
    """Dozing needs an idle agent *and* an absent user, not either alone."""

    def test_present_user_keeps_the_pet_awake(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS * 4, user_idle_ms=0), "idle")

    def test_absent_user_and_idle_agent_dozes(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(
            runtime.tick(SLEEP_AFTER_MS, user_idle_ms=SLEEP_AFTER_MS), "sleeping"
        )

    def test_user_who_just_moved_the_mouse_wakes_the_countdown(self) -> None:
        runtime = PetRuntime()
        runtime.tick(SLEEP_AFTER_MS, user_idle_ms=SLEEP_AFTER_MS - 1)
        self.assertEqual(runtime.state, "idle")

    def test_no_pointer_information_falls_back_to_the_state_clock(self) -> None:
        """Headless, or a Tk that will not report the pointer: still dozes."""

        runtime = PetRuntime()
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS, user_idle_ms=None), "sleeping")


class PokeTests(unittest.TestCase):
    def test_poke_wakes_the_pet(self) -> None:
        runtime = PetRuntime()
        runtime.tick(SLEEP_AFTER_MS)
        self.assertEqual(runtime.poke(SLEEP_AFTER_MS + 5), "idle")

    def test_poke_queues_a_hop_in_the_future(self) -> None:
        runtime = PetRuntime()
        runtime.poke(1_000)
        self.assertGreater(runtime.hop_until_ms, 1_000)

    def test_poke_does_not_change_a_working_pet(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="running"), now_ms=0)
        self.assertEqual(runtime.poke(100), "working")


if __name__ == "__main__":
    unittest.main()
