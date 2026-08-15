"""Observing the local DSH. No DSH must mean a calm pet, never a crash."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dsh_desk_pet.mapper import map_activity
from dsh_desk_pet.observer import observe_activity


class ObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_absent_dsh_is_idle(self) -> None:
        activity = observe_activity(home=self.home / "nope", process_running=False)
        self.assertEqual(map_activity(activity), "idle")

    def test_inject_file_drives_the_mapper(self) -> None:
        inject = self.home / "inject.json"
        inject.write_text(json.dumps({"kind": "blocked"}), encoding="utf-8")
        activity = observe_activity(home=self.home, inject_path=inject, process_running=False)
        self.assertEqual(map_activity(activity), "waiting")

    def test_plain_text_inject_is_accepted(self) -> None:
        inject = self.home / "inject.txt"
        inject.write_text("failed\n", encoding="utf-8")
        activity = observe_activity(home=self.home, inject_path=inject, process_running=False)
        self.assertEqual(map_activity(activity), "error")

    def test_running_process_with_fresh_session_is_working(self) -> None:
        sessions = self.home / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "log.jsonl").write_text("{}\n", encoding="utf-8")
        activity = observe_activity(home=self.home, process_running=True, now=None)
        self.assertEqual(map_activity(activity), "working")

    def test_running_process_with_stale_session_is_waiting(self) -> None:
        sessions = self.home / "sessions"
        sessions.mkdir(parents=True)
        stale = sessions / "log.txt"
        stale.write_text("nothing useful\n", encoding="utf-8")
        activity = observe_activity(
            home=self.home, process_running=True, now=stale.stat().st_mtime + 3600
        )
        self.assertEqual(map_activity(activity), "waiting")

    def test_unreadable_home_does_not_raise(self) -> None:
        activity = observe_activity(home=Path("/definitely/not/here"), process_running=False)
        self.assertEqual(map_activity(activity), "idle")


if __name__ == "__main__":
    unittest.main()
