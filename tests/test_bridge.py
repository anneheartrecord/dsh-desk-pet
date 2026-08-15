"""The desktop→page handoff. A missing or torn file must read as idle, not blow up."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dsh_desk_pet import bridge


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_publish_then_read_round_trips(self) -> None:
        bridge.publish("nautilus", "working", home=self.home, epoch_ms=42)
        payload = bridge.read(self.home)
        self.assertEqual(payload["skin"], "nautilus")
        self.assertEqual(payload["state"], "working")
        self.assertEqual(payload["epoch_ms"], 42)

    def test_publish_creates_the_directory(self) -> None:
        path = bridge.publish("whale", "idle", home=self.home / "fresh")
        self.assertTrue(path.is_file())

    def test_missing_file_reads_as_idle_whale(self) -> None:
        payload = bridge.read(self.home / "nothing-here")
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["skin"], "whale")

    def test_corrupt_file_reads_as_idle(self) -> None:
        """The page polls while the pet writes; a torn read must not 500."""

        path = bridge.state_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(bridge.read(self.home)["state"], "idle")

    def test_non_object_payload_reads_as_idle(self) -> None:
        path = bridge.state_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(bridge.read(self.home)["state"], "idle")

    def test_publish_is_atomic_and_leaves_no_temp_files(self) -> None:
        for i in range(5):
            bridge.publish("whale", "working", home=self.home, epoch_ms=i)
        leftovers = [p.name for p in bridge.state_path(self.home).parent.iterdir() if p.name.startswith(".state-")]
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")

    def test_written_file_is_valid_json_for_the_node_route(self) -> None:
        bridge.publish("jellyfish", "error", home=self.home)
        raw = bridge.state_path(self.home).read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw)["state"], "error")

    def test_clear_removes_the_file(self) -> None:
        bridge.publish("whale", "idle", home=self.home)
        bridge.clear(self.home)
        self.assertFalse(bridge.state_path(self.home).exists())

    def test_clear_is_safe_when_nothing_was_published(self) -> None:
        bridge.clear(self.home)  # must not raise


if __name__ == "__main__":
    unittest.main()
