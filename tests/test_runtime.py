"""The self-driven half of the state machine: celebration decay, dozing, pokes.

Every test drives an explicit clock. Nothing here sleeps, so five minutes of
idle behaviour is asserted in microseconds.
"""

from __future__ import annotations

import unittest

from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.runtime import HAPPY_MS, SLEEP_AFTER_MS, PetRuntime


class DefaultsTests(unittest.TestCase):
    def test_starts_on_the_deepseek_whale_idle(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.skin_id, "deepseek")
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


class DoNotDisturbTests(unittest.TestCase):
    """A user-chosen quiet mode, distinct from the doze the timers produce.

    `sleeping` is reached by nothing happening and any activity overrides it.
    This is the opposite: the user asked for quiet, so nothing the agent does
    may take it away. Only the user gives it back.
    """

    def test_starts_off(self) -> None:
        self.assertFalse(PetRuntime().do_not_disturb)

    def test_entering_shows_the_sleeping_pose(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.set_do_not_disturb(True, now_ms=1000), "sleeping")
        self.assertTrue(runtime.do_not_disturb)

    def test_activity_cannot_wake_it(self) -> None:
        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        self.assertEqual(runtime.apply_activity(AgentActivity(kind="working"), 100), "sleeping")
        self.assertEqual(runtime.apply_activity(AgentActivity(kind="error"), 200), "sleeping")
        self.assertEqual(runtime.state, "sleeping")

    def test_ticks_cannot_move_it(self) -> None:
        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        self.assertEqual(runtime.tick(SLEEP_AFTER_MS * 4, user_idle_ms=0), "sleeping")

    def test_poke_queues_a_hop_but_does_not_wake_or_clear(self) -> None:
        """Petting a sleeping pet should still feel alive without defeating DND.

        Waking on a click would silently cancel the mode with no menu
        interaction, leaving the menu item still offering to wake a pet that is
        already awake.
        """

        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        self.assertEqual(runtime.poke(100), "sleeping")
        self.assertGreater(runtime.hop_until_ms, 100)
        self.assertTrue(runtime.do_not_disturb)

    def test_leaving_wakes_the_pet(self) -> None:
        """Otherwise the pet stays visibly asleep with the menu reading awake.

        An idle observation refuses to lift `sleeping` and `tick` has no exit
        from it, so without this the pose would only change once the agent did
        real work.
        """

        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        runtime.apply_activity(AgentActivity(kind="working"), 100)
        self.assertEqual(runtime.set_do_not_disturb(False, now_ms=200), "idle")
        self.assertFalse(runtime.do_not_disturb)
        self.assertEqual(runtime.apply_activity(AgentActivity(kind="working"), 300), "working")

    def test_leaving_re_arms_the_doze_timer(self) -> None:
        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        runtime.set_do_not_disturb(False, now_ms=200)
        self.assertEqual(runtime.tick(200 + SLEEP_AFTER_MS - 1, user_idle_ms=None), "idle")
        self.assertEqual(runtime.tick(200 + SLEEP_AFTER_MS, user_idle_ms=None), "sleeping")

    def test_turning_off_when_already_off_does_not_wake(self) -> None:
        """Only a real exit from the mode should move the pet."""

        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="working"), 0)
        self.assertEqual(runtime.set_do_not_disturb(False, now_ms=100), "working")

    def test_toggling_on_twice_does_not_restart_the_sleep_loop(self) -> None:
        """Re-entering must not re-stamp the state clock.

        `_enter` short-circuits on an unchanged state, which is what preserves
        the animation phase. An unconditional stamp would restart the sleeping
        loop mid-play with the suite still green.
        """

        runtime = PetRuntime()
        runtime.set_do_not_disturb(True, now_ms=0)
        self.assertEqual(runtime.set_do_not_disturb(True, now_ms=500), "sleeping")
        self.assertEqual(runtime.state_elapsed_ms(500), 500)


if __name__ == "__main__":
    unittest.main()
