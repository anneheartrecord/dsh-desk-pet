"""Drive the shipped skin catalog and PetRuntime.set_skin."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.raster import pixel_checksum, render_ppm
from dsh_desk_pet.runtime import PetRuntime
from dsh_desk_pet.skins import DEFAULT_SKIN_ID, default_skin, list_skins


class SkinCatalogTests(unittest.TestCase):
    def test_at_least_four_skins_default_whale(self) -> None:
        skins = list_skins()
        self.assertGreaterEqual(len(skins), 4)
        ids = [skin.id for skin in skins]
        self.assertEqual(DEFAULT_SKIN_ID, "whale")
        self.assertEqual(default_skin().id, "whale")
        self.assertEqual(default_skin().name.lower(), "whale")
        self.assertIn("whale", ids)
        self.assertIn("threadcore", ids)
        self.assertIn("nautilus", ids)
        self.assertIn("jellyfish", ids)

    def test_runtime_starts_on_whale_idle(self) -> None:
        runtime = PetRuntime()
        self.assertEqual(runtime.skin_id, "whale")
        self.assertEqual(runtime.state, "idle")

    def test_set_skin_does_not_change_state(self) -> None:
        runtime = PetRuntime()
        runtime.apply_activity(AgentActivity(kind="waiting_user"))
        self.assertEqual(runtime.state, "waiting")
        returned = runtime.set_skin("jellyfish")
        self.assertEqual(returned, "waiting")
        self.assertEqual(runtime.state, "waiting")
        self.assertEqual(runtime.skin_id, "jellyfish")
        runtime.set_skin("nautilus")
        self.assertEqual(runtime.state, "waiting")
        self.assertEqual(runtime.skin_id, "nautilus")

    def test_four_skins_paint_distinct_silhouettes(self) -> None:
        checksums = {skin.id: pixel_checksum(skin.id, "idle") for skin in list_skins()}
        self.assertEqual(len(set(checksums.values())), len(checksums), checksums)

    def test_ppm_is_real_bitmap(self) -> None:
        ppm = render_ppm("whale", "idle")
        self.assertTrue(ppm.startswith(b"P6"))
        self.assertGreater(len(ppm), 1000)

    def test_four_states_paint_distinct_for_whale(self) -> None:
        states = ("idle", "working", "waiting", "error")
        checksums = {state: pixel_checksum("whale", state) for state in states}
        self.assertEqual(len(set(checksums.values())), 4, checksums)


if __name__ == "__main__":
    unittest.main()
