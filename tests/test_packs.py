"""The shipped packs — asserted against the real files, not fixtures.

These tests are the reason the art pipeline cannot silently regress: they read
`assets/` as the runtime does, so a bad chroma key, a missing state, or a PNG
that Tk 8.5 cannot open fails here rather than on the user's desktop.
"""

from __future__ import annotations

import unittest

from dsh_desk_pet import packs
from dsh_desk_pet.skins import BUILTIN_SKINS, list_skins

CORE_STATES = ("idle", "working", "waiting", "error")


class InventoryTests(unittest.TestCase):
    def test_every_shipped_skin_has_frames_on_disk(self) -> None:
        """Iterates the builtin list, not the discovered catalog.

        The catalog now includes anything a user installed, and measuring their
        art against gates written for ours fails the suite for frames we did
        not make — where the tempting repair is to loosen a gate that protects
        the shipped set.
        """

        inventory = packs.pack_inventory()
        for skin in BUILTIN_SKINS:
            self.assertIn(skin.id, inventory, f"{skin.id} is shipped but has no pack")

    def test_every_skin_covers_the_core_states(self) -> None:
        inventory = packs.pack_inventory()
        for skin_id, states in inventory.items():
            for state in CORE_STATES:
                self.assertGreater(states.get(state, 0), 0, f"{skin_id}/{state} has no frames")

    def test_idle_has_enough_frames_to_animate(self) -> None:
        """Idle is what the pet shows most of the time; a still there reads as dead."""

        for skin_id, states in packs.pack_inventory().items():
            self.assertGreaterEqual(states["idle"], 2, f"{skin_id}/idle cannot animate")

    def test_desktop_frames_are_gif_because_tk85_reads_nothing_else(self) -> None:
        for skin_id in packs.available_skins():
            for state in CORE_STATES:
                for path in packs.frames_for(skin_id, state):
                    self.assertEqual(path.suffix, ".gif", f"{path} is unreadable by Tk 8.5")

    def test_web_frames_are_png_with_matching_coverage(self) -> None:
        for skin_id in packs.available_skins():
            for state in CORE_STATES:
                desktop = packs.frames_for(skin_id, state)
                web = packs.frames_for(skin_id, state, web=True)
                self.assertEqual(
                    len(desktop), len(web), f"{skin_id}/{state} desktop and web packs disagree"
                )
                for path in web:
                    self.assertEqual(path.suffix, ".png")


class LoopTests(unittest.TestCase):
    def test_loop_returns_a_real_file(self) -> None:
        loop = packs.loop_for("deepseek", "idle")
        frame = loop.frame_at(0)
        self.assertIsNotNone(frame)
        self.assertTrue(frame.is_file())

    def test_idle_loop_actually_changes_frame(self) -> None:
        loop = packs.loop_for("deepseek", "idle")
        seen = {loop.frame_at(t) for t in range(0, loop.timeline.total_ms, 20)}
        self.assertGreater(len(seen), 1, "idle never blinks")

    def test_skin_change_keeps_the_state_and_swaps_the_art(self) -> None:
        whale = packs.loop_for("deepseek", "working").frame_at(0)
        jelly = packs.loop_for("jellyfish", "working").frame_at(0)
        self.assertNotEqual(whale, jelly)
        self.assertIn("deepseek", str(whale))
        self.assertIn("jellyfish", str(jelly))

    def test_each_state_paints_something_different(self) -> None:
        """Four states that share one image would make the mapping invisible."""

        frames = {state: packs.loop_for("deepseek", state).frame_at(0) for state in CORE_STATES}
        self.assertEqual(len(set(frames.values())), len(CORE_STATES), f"states collapsed: {frames}")


class FallbackTests(unittest.TestCase):
    def test_unknown_state_falls_back_rather_than_painting_nothing(self) -> None:
        loop = packs.loop_for("deepseek", "happy")
        self.assertIsNotNone(loop.frame_at(0), "happy has no art and no fallback")

    def test_fallback_is_reported_so_missing_art_is_visible(self) -> None:
        loop = packs.loop_for("deepseek", "happy")
        if loop.resolved_state != "happy":
            self.assertTrue(loop.is_fallback)
            self.assertEqual(loop.resolved_state, "idle")

    def test_unknown_skin_yields_an_empty_loop_not_a_crash(self) -> None:
        loop = packs.loop_for("no-such-skin", "idle")
        self.assertEqual(loop.frames, ())
        self.assertIsNone(loop.frame_at(0))


class ManifestTests(unittest.TestCase):
    def test_manifest_records_every_built_skin(self) -> None:
        skins = packs.manifest().get("skins", {})
        for skin_id in packs.available_skins():
            self.assertIn(skin_id, skins, f"{skin_id} built but not in manifest.json")

    def test_frame_size_is_sane(self) -> None:
        self.assertGreaterEqual(packs.frame_size(), 64)


if __name__ == "__main__":
    unittest.main()
