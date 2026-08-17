"""The app loop, exercised without opening a window.

`DeskPetApp` deliberately does no drawing of its own: it decides *what* to show
and hands a path to `nswindow`. That split is what lets almost all of it be
asserted here, on a machine with no display — and it is why the renderer could
be swapped from Tk to AppKit without any of the state machine changing.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from dsh_desk_pet import nswindow, packs
from dsh_desk_pet.app import DeskPetApp
from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.runtime import PetRuntime


def _app(clock_ref):
    app = DeskPetApp(PetRuntime(), clock=lambda: clock_ref[0])
    # Keep the suite out of the real ~/.dsh-desk-pet; both files are covered
    # against a temp home in test_bridge and test_prefs.
    app.publish_state = False
    app.save_prefs = False
    return app


class PaintingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ticks = [0]
        self.app = _app(self.ticks)
        self.app.render(0)

    def test_default_is_whale_idle(self) -> None:
        self.assertEqual(self.app.painted_skin, "deepseek")
        self.assertEqual(self.app.painted_state, "idle")

    def test_paints_rgba_frames_now_that_appkit_can_composite_them(self) -> None:
        """Tk 8.5 could only read GIF, which capped the pet at a 1-bit matte."""

        self.assertIsNotNone(self.app.painted_frame)
        self.assertEqual(self.app.painted_frame.suffix, ".png")
        self.assertIn("assets/web", str(self.app.painted_frame))

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

    def test_next_skin_cycles_and_returns(self) -> None:
        first = self.app.runtime.skin_id
        seen = {first}
        for _ in range(len(packs.available_skins())):
            self.app.next_skin()
            seen.add(self.app.runtime.skin_id)
        self.assertEqual(self.app.runtime.skin_id, first, "cycle did not come back around")
        self.assertGreater(len(seen), 1)

    def test_motion_moves_the_pet_between_ticks(self) -> None:
        """Breath is what keeps a held frame from looking like a screenshot."""

        offsets = {(round(self.app._motion(t).dx, 2), round(self.app._motion(t).dy, 2))
                   for t in range(0, 1200, 60)}
        self.assertGreater(len(offsets), 3, "the pet never moves")


class HitTestTests(unittest.TestCase):
    """Per-pixel-ish click-through: the window must not eat the whole desktop
    rectangle it covers."""

    def setUp(self) -> None:
        self.app = _app([0])

    def test_centre_is_on_the_pet(self) -> None:
        centre = self.app.canvas_side / 2
        self.assertTrue(self.app.is_on_pet(centre, centre))

    def test_corners_fall_through(self) -> None:
        for x, y in ((1, 1), (self.app.canvas_side - 1, 1), (1, self.app.canvas_side - 1)):
            self.assertFalse(self.app.is_on_pet(x, y), f"({x},{y}) counted as the pet")

    def test_every_skin_has_a_subject_box(self) -> None:
        for skin in packs.available_skins():
            self.assertIsNotNone(packs.subject_box(skin), f"{skin} has no subject box")


class PanelContentTests(unittest.TestCase):
    """What the click-panel says, asserted without opening one."""

    def setUp(self) -> None:
        self.app = _app([0])

    def test_rows_are_plain_data(self) -> None:
        rows, footer = self.app.panel_rows()
        self.assertIsInstance(rows, list)
        self.assertIsInstance(footer, str)
        for active, title, badge, age in rows:
            self.assertIsInstance(active, bool)
            self.assertTrue(title, "a row with no label is not worth drawing")
            self.assertIsInstance(badge, str)
            self.assertIsInstance(age, str)

    def test_a_live_session_is_badged_with_what_the_pet_is_doing(self) -> None:
        """The filesystem knows a session moved; only the pet knows why."""

        self.app.apply_activity(AgentActivity(kind="running"))
        rows, _ = self.app.panel_rows()
        for active, _title, badge, _age in rows:
            if active:
                self.assertEqual(badge, "Working")

    def test_idle_rows_carry_no_badge(self) -> None:
        rows, _ = self.app.panel_rows()
        for active, _title, badge, _age in rows:
            if not active:
                self.assertEqual(badge, "")

    def test_panel_is_not_built_before_the_window(self) -> None:
        self.assertIsNone(self.app.panel)
        self.app.toggle_panel()
        self.assertIsNone(self.app.panel, "panel opened with nowhere to anchor it")


class ProbeTests(unittest.TestCase):
    def test_probe_needs_no_display(self) -> None:
        app = _app([0])
        self.assertEqual(app.probe("threadcore"), 0)


@unittest.skipUnless(nswindow.available(), "AppKit unavailable on this host")
class RendererTests(unittest.TestCase):
    def test_the_renderer_is_reachable_through_ctypes(self) -> None:
        """No PyObjC, no Homebrew Python — the plugin installs with nothing."""

        self.assertTrue(nswindow.available())

    def test_window_geometry_round_trips_through_appkit_coordinates(self) -> None:
        """AppKit's origin is bottom-left and everything else here is top-left;
        that conversion lives in one place and is easy to get backwards."""

        window = nswindow.PetWindow(120, 120, x=300, y=250)
        try:
            self.assertEqual(window.position(), (300, 250))
            window.move_to(410, 360)
            self.assertEqual(window.position(), (410, 360))
        finally:
            window.close()

    def test_panel_opens_and_closes(self) -> None:
        panel = nswindow.PanelWindow()
        try:
            self.assertFalse(panel.visible)
            panel.show([(True, "session", "Working", "just now")], x=200, y=200, footer="2 others")
            self.assertTrue(panel.visible)
            panel.hide()
            self.assertFalse(panel.visible)
        finally:
            panel.close()

    def test_panel_attaches_as_a_child_and_travels_with_the_pet(self) -> None:
        """Dragging cannot be followed from our own loop: AppKit's drag loop
        owns the thread until the mouse comes up. A child window needs no
        following."""

        pet = nswindow.PetWindow(160, 160, x=300, y=300)
        panel = nswindow.PanelWindow()
        try:
            panel.show([(True, "row", "Working", "now")], x=250, y=480)
            panel.attach_to(pet)
            before = panel._rect(panel._window, panel.rt.sel("frame")).x
            pet.move_to(600, 350)
            pet.pump(0.05)
            after = panel._rect(panel._window, panel.rt.sel("frame")).x
            self.assertEqual(after - before, 300, "panel did not travel with the pet")
        finally:
            panel.close()
            pet.close()

    def test_panel_still_travels_after_being_closed_and_reopened(self) -> None:
        """The bug the test above could not see, because it never hid the panel.

        `orderOut:` takes a window out of its parent's child list, so attaching
        once at creation only held for the first open. Every open after that
        looked right until the pet was dragged, at which point the list stayed
        behind. This walks the sequence a user actually performs: open, close,
        open again, then move.
        """

        pet = nswindow.PetWindow(160, 160, x=300, y=300)
        panel = nswindow.PanelWindow()
        try:
            rows = [(True, "row", "Working", "now")]
            panel.show(rows, x=250, y=480)
            panel.attach_to(pet)
            panel.hide()
            panel.show(rows, x=250, y=480)

            before = panel._rect(panel._window, panel.rt.sel("frame")).x
            pet.move_to(600, 350)
            pet.pump(0.05)
            after = panel._rect(panel._window, panel.rt.sel("frame")).x
            self.assertEqual(
                after - before, 300,
                "panel stopped following the pet after being reopened",
            )
        finally:
            panel.close()
            pet.close()

    def test_panel_redraw_does_not_leak_layers(self) -> None:
        panel = nswindow.PanelWindow()
        try:
            for index in range(6):
                panel.show([(False, f"row {index}", "", "1m ago")], x=100, y=100)
            self.assertLessEqual(len(panel._layers), 8, "old rows were never removed")
        finally:
            panel.close()

    def test_window_shows_a_frame_without_raising(self) -> None:
        frame = packs.loop_for("deepseek", "idle", web=True).frame_at(0)
        self.assertIsInstance(frame, Path)
        window = nswindow.PetWindow(120, 120, x=200, y=200)
        try:
            window.set_image(frame)
            window.pump(0.05)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
