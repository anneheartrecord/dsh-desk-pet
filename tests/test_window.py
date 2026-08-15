"""Drive the real Tk window, unmapped.

Not a stub. Under a sandbox or over SSH the only Tk call that blocks is mapping
the window (`deiconify`), so building it withdrawn exercises the genuine
article — including Tk 8.5's GIF decoder, which is the whole reason the art
pipeline emits GIF. A fake Tk would happily "load" a PNG and prove nothing.
"""

from __future__ import annotations

import unittest

from dsh_desk_pet.app import DeskPetApp
from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.runtime import PetRuntime

try:  # A machine with no Tk at all should skip, not fail.
    import tkinter

    tkinter.Tk().destroy()
    HAVE_TK = True
except Exception:  # pragma: no cover - depends on the host
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "no usable Tk on this host")
class WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ticks = [0]
        self.app = DeskPetApp(PetRuntime(), clock=lambda: self.ticks[0])
        # Keep the suite out of the real ~/.dsh-desk-pet; the handoff itself is
        # covered in test_bridge against a temp home.
        self.app.publish_state = False
        self.app._build(mapped=False)
        self.addCleanup(self.app.quit)

    def test_window_is_borderless_transparent_and_topmost(self) -> None:
        self.assertTrue(self.app._root.overrideredirect(), "pet still has window chrome")
        self.assertTrue(self.app.always_on_top(), "pet will sink behind the browser")
        self.assertTrue(self.app.transparent, "pet is painted on an opaque plate")

    def test_default_is_whale_idle(self) -> None:
        self.assertEqual(self.app.painted_skin, "whale")
        self.assertEqual(self.app.painted_state, "idle")

    def test_paints_a_generated_frame_not_a_drawing(self) -> None:
        self.assertIsNotNone(self.app.painted_frame)
        self.assertEqual(self.app.painted_frame.suffix, ".gif")
        self.assertIn("assets", str(self.app.painted_frame))

    def test_idle_paints_more_than_one_frame_over_a_cycle(self) -> None:
        seen = set()
        for t in range(0, 3200, 40):
            self.ticks[0] = t
            self.app.render(t)
            seen.add(self.app.painted_frame)
        self.assertGreater(len(seen), 1, "the pet is frozen on one frame")

    def test_skin_change_keeps_state_and_swaps_art(self) -> None:
        self.app.apply_activity(AgentActivity(kind="running"))
        before = self.app.painted_frame
        self.assertEqual(self.app.select_skin("nautilus"), "working")
        self.assertEqual(self.app.painted_state, "working")
        self.assertNotEqual(self.app.painted_frame, before)
        self.assertIn("nautilus", str(self.app.painted_frame))

    def test_every_state_paints_distinct_art(self) -> None:
        painted = {}
        for kind, state in (("none", "idle"), ("running", "working"), ("blocked", "waiting"), ("failed", "error")):
            self.app.apply_activity(AgentActivity(kind=kind))
            self.assertEqual(self.app.painted_state, state)
            painted[state] = self.app.painted_frame
        self.assertEqual(len(set(painted.values())), len(painted), f"states share art: {painted}")

    def test_sprite_moves_between_ticks(self) -> None:
        """Breath is what keeps a one-frame state from looking like a screenshot."""

        self.app.apply_activity(AgentActivity(kind="running"))
        positions = set()
        for t in range(0, 1200, 60):
            self.ticks[0] = t
            self.app.render(t)
            positions.add(tuple(self.app._canvas.coords(self.app._sprite_id)))
        self.assertGreater(len(positions), 3, "the sprite never moves")

    def test_photo_cache_reuses_images(self) -> None:
        for t in range(0, 4000, 25):
            self.app.render(t)
        self.assertLessEqual(len(self.app._cache), 8, "leaking a PhotoImage per frame")

    def test_quit_is_idempotent(self) -> None:
        self.app.quit()
        self.app.quit()
        self.assertIsNone(self.app._root)


@unittest.skipUnless(HAVE_TK, "no usable Tk on this host")
class ProbeTests(unittest.TestCase):
    def test_probe_succeeds_without_mapping_a_window(self) -> None:
        app = DeskPetApp(PetRuntime())
        app.publish_state = False
        self.assertEqual(app.probe("threadcore"), 0)


if __name__ == "__main__":
    unittest.main()
