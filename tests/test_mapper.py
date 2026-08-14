"""Drive the shipped map_activity — not a reimplementation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsh_desk_pet.mapper import AgentActivity, map_activity
from dsh_desk_pet.runtime import PetRuntime


class MapActivityTests(unittest.TestCase):
    def test_no_activity_is_idle(self) -> None:
        self.assertEqual(map_activity(None), "idle")
        self.assertEqual(map_activity(AgentActivity(kind="none")), "idle")
        self.assertEqual(map_activity(AgentActivity(kind="")), "idle")

    def test_in_progress_is_working(self) -> None:
        self.assertEqual(map_activity(AgentActivity(kind="running")), "working")
        self.assertEqual(map_activity(AgentActivity(kind="in_progress")), "working")
        self.assertEqual(map_activity(AgentActivity(kind="working")), "working")

    def test_blocked_on_user_is_waiting(self) -> None:
        self.assertEqual(map_activity(AgentActivity(kind="waiting_user")), "waiting")
        self.assertEqual(map_activity(AgentActivity(kind="approval")), "waiting")
        self.assertEqual(map_activity(AgentActivity(kind="needs_input")), "waiting")

    def test_failed_run_is_error(self) -> None:
        self.assertEqual(map_activity(AgentActivity(kind="failed")), "error")
        self.assertEqual(map_activity(AgentActivity(kind="errored")), "error")
        self.assertEqual(map_activity(AgentActivity(kind="error")), "error")

    def test_completion_returns_to_idle(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="running"))
        self.assertEqual(runtime.state, "working")
        runtime.apply_activity(AgentActivity(kind="completed"))
        self.assertEqual(runtime.state, "idle")
        self.assertEqual(map_activity(AgentActivity(kind="done")), "idle")
        self.assertEqual(map_activity(AgentActivity(kind="success")), "idle")


if __name__ == "__main__":
    unittest.main()
