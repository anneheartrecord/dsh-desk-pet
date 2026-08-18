"""The app loop, exercised without opening a window.

`DeskPetApp` deliberately does no drawing of its own: it decides *what* to show
and hands a path to `nswindow`. That split is what lets almost all of it be
asserted here, on a machine with no display — and it is why the renderer could
be swapped from Tk to AppKit without any of the state machine changing.
"""

from __future__ import annotations

import ctypes
import os
import signal
import threading
import unittest
from pathlib import Path

from dsh_desk_pet import nswindow, packs
from dsh_desk_pet.app import DeskPetApp
from dsh_desk_pet.mapper import AgentActivity
from dsh_desk_pet.runtime import PetRuntime
from dsh_desk_pet.skins import list_skins


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
        # Sized from the catalog `next_skin` actually walks, which now includes
        # any skin the user installed — `available_skins` enumerates the shipped
        # tree only, so it would come up short by exactly those.
        for _ in range(len(list_skins())):
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


class MenuModelTests(unittest.TestCase):
    """The menu as plain data.

    Computed here rather than in the window for the same reason `panel_rows`
    is: what the menu *says* is then testable with no display, and the AppKit
    half is left with nothing to decide.
    """

    def setUp(self) -> None:
        self.clock = [0]
        self.app = _app(self.clock)

    def _by_action(self, action):
        return next(e for e in self.app.menu_model() if e.action == action)

    def test_order_and_shape_match_the_menu_spec(self) -> None:
        model = self.app.menu_model()
        self.assertEqual(
            [e.kind for e in model],
            ["item", "separator", "item", "submenu", "separator",
             "item", "item", "separator", "item", "separator", "item"],
        )
        self.assertEqual(
            [e.action for e in model if e.kind == "item"],
            ["dnd", "dashboard", "menu_bar", "dock", "updates", "quit"],
        )
        self.assertEqual(sum(1 for e in model if e.kind == "separator"), 4)

    def test_sleep_entry_is_checked_only_while_the_mode_is_on(self) -> None:
        self.assertFalse(self._by_action("dnd").checked)
        self.app.runtime.set_do_not_disturb(True, now_ms=self.clock[0])
        entry = self._by_action("dnd")
        self.assertTrue(entry.checked)
        self.assertEqual(entry.title, "Sleep (Do Not Disturb)",
                         "the title is stable; the checkmark carries the state")

    def test_skin_submenu_lists_every_skin_with_exactly_one_ticked(self) -> None:
        submenu = next(e for e in self.app.menu_model() if e.kind == "submenu")
        ids = [child.action for child in submenu.children]
        self.assertEqual(ids, [f"skin:{skin.id}" for skin in list_skins()])
        ticked = [c for c in submenu.children if c.checked]
        self.assertEqual(len(ticked), 1)
        self.assertEqual(ticked[0].action, f"skin:{self.app.runtime.skin_id}")

    def test_selecting_a_skin_moves_the_tick(self) -> None:
        self.app.select_skin("jellyfish")
        submenu = next(e for e in self.app.menu_model() if e.kind == "submenu")
        ticked = [c for c in submenu.children if c.checked]
        self.assertEqual([c.action for c in ticked], ["skin:jellyfish"])

    def test_visibility_entries_are_enabled_in_every_combination(self) -> None:
        """There is deliberately no rule keeping one of them on.

        The reference implementation disables the last remaining affordance
        because its pet can be hidden. Ours cannot, and right-click always
        reaches the menu, so a guard here would strand a Dock icon the user
        could not remove.
        """

        for menu_bar in (False, True):
            for dock in (False, True):
                with self.subTest(menu_bar=menu_bar, dock=dock):
                    self.app.prefs.show_menu_bar = menu_bar
                    self.app.prefs.show_dock = dock
                    model = self.app.menu_model()
                    self.assertTrue(all(e.enabled for e in model))
                    self.assertEqual(self._by_action("menu_bar").checked, menu_bar)
                    self.assertEqual(self._by_action("dock").checked, dock)

    def test_both_off_is_a_well_formed_menu(self) -> None:
        self.app.prefs.show_menu_bar = False
        self.app.prefs.show_dock = False
        model = self.app.menu_model()
        self.assertEqual(len(model), 11)
        self.assertTrue(all(e.enabled for e in model))

    def test_dashboard_entry_names_what_the_click_will_do(self) -> None:
        """A one-way Open would be the only item in the menu that can do nothing."""

        self.assertEqual(self._by_action("dashboard").title, "Open Dashboard")

        class _Panel:
            visible = True

        self.app.panel = _Panel()
        self.assertEqual(self._by_action("dashboard").title, "Hide Dashboard")

    def test_every_item_carries_an_action_and_separators_do_not(self) -> None:
        for entry in self.app.menu_model():
            with self.subTest(kind=entry.kind, title=entry.title):
                if entry.kind == "item":
                    self.assertTrue(entry.action, "an item with no action cannot be dispatched")
                else:
                    self.assertEqual(entry.action, "")


class MenuActionTests(unittest.TestCase):
    """Dispatching a picked entry. The window knows the action key and nothing else."""

    def setUp(self) -> None:
        self.clock = [0]
        self.app = _app(self.clock)

    def test_every_action_the_model_offers_can_be_dispatched(self) -> None:
        """An action string with no handler is a menu item that does nothing."""

        actions = []
        for entry in self.app.menu_model():
            if entry.kind == "item":
                actions.append(entry.action)
            for child in entry.children:
                actions.append(child.action)
        for action in actions:
            with self.subTest(action=action):
                self.assertTrue(self.app.can_handle_menu(action), f"no handler for {action}")

    def test_sleep_action_toggles_the_mode_both_ways(self) -> None:
        self.app.on_menu_action("dnd")
        self.assertTrue(self.app.runtime.do_not_disturb)
        self.app.on_menu_action("dnd")
        self.assertFalse(self.app.runtime.do_not_disturb)

    def test_skin_action_selects_that_skin(self) -> None:
        self.app.on_menu_action("skin:nautilus")
        self.assertEqual(self.app.runtime.skin_id, "nautilus")

    def test_visibility_actions_toggle_and_persist_the_pref(self) -> None:
        self.app.on_menu_action("menu_bar")
        self.assertTrue(self.app.prefs.show_menu_bar)
        self.app.on_menu_action("dock")
        self.assertTrue(self.app.prefs.show_dock)
        self.app.on_menu_action("dock")
        self.assertFalse(self.app.prefs.show_dock)

    def test_dashboard_action_shows_the_panel_and_repeating_it_does_not_close(self) -> None:
        """The regression the plan named: reusing the toggle would make the
        menu item close the dashboard for anyone who already had it open."""

        calls = []
        self.app.show_panel = lambda: calls.append("show")  # type: ignore[method-assign]
        self.app.on_menu_action("dashboard")
        self.app.on_menu_action("dashboard")
        self.assertEqual(calls, ["show", "show"])

    def test_dashboard_action_hides_when_already_open(self) -> None:
        class _Panel:
            visible = True

        self.app.panel = _Panel()
        hidden = []
        self.app.hide_panel = lambda: hidden.append("hide")  # type: ignore[method-assign]
        self.app.on_menu_action("dashboard")
        self.assertEqual(hidden, ["hide"])

    def test_quit_stops_the_run_loop(self) -> None:
        self.app._running = True
        self.app.on_menu_action("quit")
        self.assertFalse(self.app._running)

    def test_unknown_action_is_ignored_rather_than_raising(self) -> None:
        """This runs inside an Objective-C callback, where a raise unwinds into
        AppKit with nothing to catch it."""

        self.app.on_menu_action("nonsense")
        self.app.on_menu_action("skin:does-not-exist")


class PanelShowHideTests(unittest.TestCase):
    """`toggle_panel` split so the menu has a one-way Open."""

    def test_show_is_idempotent_and_toggle_still_alternates(self) -> None:
        clock = [0]
        app = _app(clock)
        seen = []
        app._present_panel = lambda: seen.append("present")  # type: ignore[method-assign]
        # `show_panel` needs a pet window to anchor against; the panel is a
        # child of it. Stubbed rather than created, so this stays headless.
        app.window = object()  # type: ignore[assignment]

        class _Panel:
            visible = False

        app.panel = _Panel()
        app.show_panel()
        app.show_panel()
        self.assertEqual(seen, ["present", "present"], "Open must never close")

        app.toggle_panel()
        self.assertEqual(seen, ["present", "present", "present"])
        app.panel.visible = True
        hidden = []
        app.panel.hide = lambda: hidden.append("hide")
        app.toggle_panel()
        self.assertEqual(hidden, ["hide"], "toggle still alternates")


class ShutdownTests(unittest.TestCase):
    """SIGTERM must leave the same way a menu Quit does.

    `--stop` and the plugin teardown both send SIGTERM. Without a handler the
    process dies outright, `quit` never runs, and the published state file
    survives — so the next launch reads a file that still looks fresh and
    refuses to start until the staleness window has passed.
    """

    def test_sigterm_stops_the_loop_rather_than_killing_the_process(self) -> None:
        clock = [0]
        app = _app(clock)
        app._running = True
        app.install_signal_handlers()
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.assertFalse(app._running, "the loop should have been asked to leave")

    def test_installing_off_the_main_thread_does_not_raise(self) -> None:
        clock = [0]
        app = _app(clock)
        errors = []

        def install():
            try:
                app.install_signal_handlers()
            except Exception as exc:  # pragma: no cover - the point is that it does not
                errors.append(exc)

        thread = threading.Thread(target=install)
        thread.start()
        thread.join()
        self.assertEqual(errors, [])


class ClickUnderDoNotDisturbTests(unittest.TestCase):
    """The one do-not-disturb guarantee that does not live in the state machine.

    `_on_click` pokes the runtime and then opens the panel. The runtime latch
    stops the poke waking the pet, but nothing stops the panel opening — and it
    should not: the mode quiets the pet, it does not make it unresponsive. That
    holds by construction today, so this is a forward guard rather than a test
    that was ever red. It exists because the menu units edit exactly this
    handler, and an early return under do-not-disturb would otherwise be
    invisible to the suite.
    """

    def test_click_still_opens_the_panel_and_does_not_wake(self) -> None:
        clock = [0]
        app = _app(clock)
        opened = []
        app.toggle_panel = lambda: opened.append(True)  # type: ignore[method-assign]

        app.runtime.set_do_not_disturb(True, now_ms=clock[0])
        clock[0] = 1000
        app._on_click()

        self.assertEqual(len(opened), 1, "the panel must still respond under do-not-disturb")
        self.assertEqual(app.runtime.state, "sleeping", "the click must not wake the pet")
        self.assertTrue(app.runtime.do_not_disturb, "the click must not clear the mode")
        self.assertGreater(app.runtime.hop_until_ms, clock[0], "the bounce should still be queued")


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

    def test_builds_a_real_menu_from_the_model(self) -> None:
        """Built and inspected, never popped.

        `popUpContextMenu:` runs a modal tracking loop that does not return
        until the menu is dismissed, so a test that popped one would hang the
        suite rather than fail. That the loop resumes afterwards is on the
        hand-verified gate.
        """

        clock = [0]
        app = _app(clock)
        pet = nswindow.PetWindow(160, 160, x=300, y=300)
        try:
            model = app.menu_model()
            menu = pet.build_menu(model)
            rt = pet.rt
            count = pet._long_msg(menu, rt.sel("numberOfItems"))
            self.assertEqual(count, len(model))

            item_at = rt.sig(ctypes.c_void_p, ctypes.c_long)
            for index, entry in enumerate(model):
                item = item_at(menu, rt.sel("itemAtIndex:"), index)
                is_sep = pet.rt.sig(ctypes.c_bool)(item, rt.sel("isSeparatorItem"))
                self.assertEqual(bool(is_sep), entry.kind == "separator",
                                 f"entry {index} separator mismatch")
                if entry.kind == "separator":
                    continue
                state = pet._long_msg(item, rt.sel("state"))
                self.assertEqual(bool(state), entry.checked, f"entry {index} check state")
                if entry.kind == "submenu":
                    sub = pet._ptr(item, rt.sel("submenu"))
                    self.assertTrue(sub, "submenu entry has no submenu attached")
                    self.assertEqual(
                        pet._long_msg(sub, rt.sel("numberOfItems")), len(entry.children))
        finally:
            pet.close()

    def test_every_action_key_round_trips_through_its_tag(self) -> None:
        """The tag is the only thing carried across the ObjC boundary."""

        clock = [0]
        app = _app(clock)
        pet = nswindow.PetWindow(160, 160, x=300, y=300)
        try:
            model = app.menu_model()
            pet._menu_actions.clear()
            pet.build_menu(model)
            expected = [e.action for e in model if e.kind == "item"]
            expected += [c.action for e in model for c in e.children]
            self.assertEqual(sorted(pet._menu_actions.values()), sorted(expected))
            for action in pet._menu_actions.values():
                self.assertTrue(app.can_handle_menu(action), f"unreachable action {action}")
        finally:
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
