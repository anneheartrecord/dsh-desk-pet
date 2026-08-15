"""Activity labels in, display states out. Nothing else."""

from __future__ import annotations

import unittest

from dsh_desk_pet.mapper import STATES, AgentActivity, map_activity


class MapActivityTests(unittest.TestCase):
    def test_no_activity_is_idle(self) -> None:
        self.assertEqual(map_activity(None), "idle")
        self.assertEqual(map_activity(AgentActivity(kind="")), "idle")

    def test_in_progress_is_working(self) -> None:
        for kind in ("running", "in_progress", "tool", "thinking"):
            self.assertEqual(map_activity(AgentActivity(kind=kind)), "working", kind)

    def test_blocked_on_user_is_waiting(self) -> None:
        for kind in ("waiting", "blocked", "approval", "needs_input", "permission"):
            self.assertEqual(map_activity(AgentActivity(kind=kind)), "waiting", kind)

    def test_failed_run_is_error(self) -> None:
        for kind in ("error", "failed", "aborted"):
            self.assertEqual(map_activity(AgentActivity(kind=kind)), "error", kind)

    def test_completion_is_happy_not_idle(self) -> None:
        """The one moment worth reacting to; the runtime decays it back to idle."""

        for kind in ("completed", "done", "success"):
            self.assertEqual(map_activity(AgentActivity(kind=kind)), "happy", kind)

    def test_labels_are_case_and_space_insensitive(self) -> None:
        self.assertEqual(map_activity(AgentActivity(kind="  RUNNING ")), "working")

    def test_unknown_label_falls_back_to_idle(self) -> None:
        """A stale observer must not be able to invent a state with no art."""

        self.assertEqual(map_activity(AgentActivity(kind="teleporting")), "idle")

    def test_mapper_never_returns_a_state_outside_the_catalog(self) -> None:
        for kind in ("running", "blocked", "failed", "done", "", "nonsense"):
            self.assertIn(map_activity(AgentActivity(kind=kind)), STATES)


if __name__ == "__main__":
    unittest.main()
