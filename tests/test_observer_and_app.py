"""Observer fallback + the same select_skin API the desktop UI uses."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsh_desk_pet.app import DeskPetApp
from dsh_desk_pet.mapper import AgentActivity, map_activity
from dsh_desk_pet.observer import observe_activity
from dsh_desk_pet.runtime import PetRuntime


class ObserverTests(unittest.TestCase):
    def test_absent_dsh_is_idle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            activity = observe_activity(home=home, process_running=False, now=1_700_000_000)
            self.assertEqual(activity.kind, "none")
            self.assertEqual(map_activity(activity), "idle")

    def test_inject_file_drives_mapper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            hint = home / "pet-activity.json"
            hint.write_text(json.dumps({"kind": "failed"}), encoding="utf-8")
            activity = observe_activity(home=home, process_running=False)
            self.assertEqual(map_activity(activity), "error")

    def test_recent_session_plus_process_is_working(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            session = home / "sessions" / "s1"
            session.mkdir(parents=True)
            payload = session / "session.jsonl"
            payload.write_text('{"type":"tool"}\n', encoding="utf-8")
            activity = observe_activity(home=home, process_running=True, now=payload.stat().st_mtime)
            self.assertEqual(map_activity(activity), "working")

    def test_process_without_recent_writes_is_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            activity = observe_activity(home=home, process_running=True, now=1_700_000_000)
            self.assertEqual(map_activity(activity), "waiting")


class AppWiringTests(unittest.TestCase):
    def test_select_skin_uses_runtime_and_keeps_state(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="running"))
        app = DeskPetApp(runtime)
        returned = app.select_skin("threadcore")
        self.assertEqual(returned, "working")
        self.assertEqual(app.runtime.state, "working")
        self.assertEqual(app.runtime.skin_id, "threadcore")
        self.assertEqual(app.painted_skin, "threadcore")
        self.assertEqual(app.painted_state, "working")

    def test_apply_activity_paints_error(self) -> None:
        app = DeskPetApp(PetRuntime())
        app.apply_activity(AgentActivity(kind="failed"))
        self.assertEqual(app.painted_state, "error")
        self.assertEqual(app.painted_skin, "whale")


if __name__ == "__main__":
    unittest.main()
