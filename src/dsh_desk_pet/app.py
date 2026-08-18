"""The desktop pet: an AppKit window driven by the shared state machine.

Deliberately not an in-page widget. The point of this plugin is a pet that sits
*over* the DSH tab and every other window, the way the Codex pet and
claw-on-desk do, which a `<div>` in the page can never do.

This file owns the loop and nothing else. `observer` decides what DSH is doing,
`runtime` decides what the pet should therefore be, `packs` and `anim` decide
which frame that means right now, `nswindow` puts it on screen, and `bridge`
publishes it for the instance guard and for `--stop`. Each of those is testable
without a display; this is the only part that needs one.

The renderer is AppKit rather than Tk because macOS ships Tk 8.5.9 from 2010,
and on macOS 26 its drawing path no longer reaches the screen — see
`nswindow.py`. Moving to AppKit also let the desktop pet switch from the 1-bit
GIF matte to the RGBA PNGs, which is why the edges are soft now.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import bridge, nswindow, packs, prefs as prefs_store, sessions, updates
from .anim import motion_for
from .mapper import AgentActivity
from .observer import observe_activity
from .runtime import PetRuntime
from .skins import DEFAULT_SKIN_ID, get_skin, is_known_skin, list_skins

# Room around the sprite so the breath and hop never clip at the window edge.
MARGIN = 22
FRAME_MS = 33
POLL_MS = 600
# Republish the state file at least this often even when nothing changed, so
# the page can tell "sitting still" from "process died".
HEARTBEAT_MS = 2000
# Re-assert level and Spaces periodically; a Space change can drop them.
TOPMOST_MS = 4000
# How often to ask AppKit where the pointer is; the doze threshold is 90s.
POINTER_MS = 400
# How many sessions the click-panel lists before summarising the rest.
PANEL_ROWS = 5
# Set DSH_PET_DEBUG=1 to trace the observe -> state loop on stderr.
DEBUG = os.environ.get("DSH_PET_DEBUG") == "1"


def now_ms() -> int:
    return int(time.monotonic() * 1000)


@dataclass(frozen=True)
class MenuEntry:
    """One row of the right-click menu, as data.

    The window turns these into `NSMenuItem`s and decides nothing. Keeping the
    shape here is what lets the menu's contents be asserted with no display,
    the same trick `panel_rows` uses.
    """

    kind: str  # "item" | "separator" | "submenu"
    title: str = ""
    action: str = ""
    checked: bool = False
    enabled: bool = True
    children: tuple["MenuEntry", ...] = ()


class DeskPetApp:
    """Owns the pet's loop. All state transitions go through PetRuntime."""

    def __init__(
        self,
        runtime: PetRuntime | None = None,
        *,
        clock=now_ms,
        prefs: prefs_store.Prefs | None = None,
    ) -> None:
        self.prefs = (prefs or prefs_store.Prefs()).clamped()
        self.clock = clock
        # Seed from the same clock the app runs on. A runtime starting at t=0
        # against a monotonic clock reads its first tick as minutes of elapsed
        # idle time, and the pet launches already asleep.
        self.runtime = runtime or PetRuntime(skin_id=self.prefs.skin_id, now_ms=clock())
        self.painted_skin = ""
        self.painted_state = ""
        self.painted_frame: Path | None = None
        self.window: nswindow.PetWindow | None = None
        self.panel: nswindow.PanelWindow | None = None
        self._running = False
        self._published: tuple[str, str] | None = None
        self._published_at_ms = -HEARTBEAT_MS
        self._topmost_at_ms = -TOPMOST_MS
        self._drawn_frame: Path | None = None
        # The update checker replaces this with a real status in its own unit.
        # Until then the menu shows the resting label rather than a state
        # nothing can produce.
        self.update_label = "Check for Updates"
        self._update_checked_ms = -updates.CACHE_MS
        self._update_thread: threading.Thread | None = None
        self._pointer_seen: tuple[float, float] | None = None
        self._pointer_moved_ms = 0
        self._pointer_checked_ms = -400
        self._latest_activity: AgentActivity | None = None
        self._watcher: threading.Thread | None = None
        self._stop_watch = threading.Event()
        self.publish_state = True
        self.save_prefs = True

    # ------------------------------------------------------------- geometry

    @property
    def sprite_side(self) -> int:
        """Any scale, not just halves.

        Tk could only zoom a PhotoImage by whole factors, which is why this used
        to be a choice between full size and half. AppKit resamples smoothly, so
        the size is now a plain multiplier.
        """

        return max(48, round(packs.frame_size() * self.prefs.scale))

    @property
    def canvas_side(self) -> int:
        return self.sprite_side + MARGIN * 2

    def is_on_pet(self, x: float, y: float) -> bool:
        """Is this window point on the character, or on empty air?

        Answered from the skin's subject box, recorded at build time. AppKit
        asks this before delivering a click, so `False` lets the click reach
        whatever is behind the pet — the window stops being an invisible
        rectangle that swallows everything landing on it.
        """

        box = packs.subject_box(self.runtime.skin_id)
        if box is None:
            return True
        scale = self.sprite_side / max(1, packs.frame_size())
        x0, y0, x1, y1 = (v * scale + MARGIN for v in box)
        return x0 <= x <= x1 and y0 <= y <= y1

    # ------------------------------------------------------------ behaviour

    def select_skin(self, skin_id: str) -> str:
        """Picker entry. Changing skin must never change state."""

        state = self.runtime.set_skin(skin_id)
        self.prefs.skin_id = skin_id
        self._save_prefs()
        self._drawn_frame = None  # force a repaint even mid-hold
        self.render(self.clock())
        return state

    def next_skin(self) -> str:
        skins = [skin.id for skin in list_skins()]
        try:
            index = skins.index(self.runtime.skin_id)
        except ValueError:
            index = -1
        return self.select_skin(skins[(index + 1) % len(skins)])

    def apply_activity(self, activity: AgentActivity | None) -> str:
        state = self.runtime.apply_activity(activity, self.clock())
        self.render(self.clock())
        return state

    def _on_click(self) -> None:
        """A poke, and a look at what DSH is up to.

        Clicking a desk pet should tell you something. The panel is the answer
        to the question the pet raises just by sitting there — which sessions
        are running, and which one is busy.
        """

        self.runtime.poke(self.clock())
        self.toggle_panel()

    def panel_rows(self) -> tuple[list[tuple[bool, str, str, str]], str]:
        """(rows, footer) for the session panel.

        Kept here rather than in the window so what the panel *says* is
        testable without a display.
        """

        shown = sessions.list_sessions(limit=PANEL_ROWS)
        rows = []
        for session in shown:
            badge = ""
            if session.active:
                # Only the pet's own state can say what a live session is
                # doing; the filesystem only knows that it moved.
                badge = {"working": "Working", "waiting": "Waiting",
                         "error": "Error"}.get(self.runtime.state, "Active")
            rows.append((session.active, session.title, badge, session.age_label()))

        total = sessions.total_count()
        hidden = max(0, total - len(shown))
        return rows, (f"{hidden} other session{'s' if hidden != 1 else ''}" if hidden else "")

    def menu_model(self) -> tuple[MenuEntry, ...]:
        """The right-click menu, in the order it is shown.

        Every entry is enabled. The two visibility toggles are deliberately
        independent: the reference implementation disables whichever one is
        last, because its pet can be hidden and they are the only ways back to
        the menu, but this pet cannot be hidden and right-click always reaches
        it. Carrying that rule across would strand a Dock icon with no way to
        remove it.
        """

        panel_open = self.panel is not None and self.panel.visible
        skins = tuple(
            MenuEntry(
                kind="item",
                title=skin.name,
                action=f"skin:{skin.id}",
                checked=skin.id == self.runtime.skin_id,
            )
            for skin in list_skins()
        )
        return (
            # A checkmark, not a label swap: the other two toggles carry one, and
            # an inverse verb alone never shows the mode as currently on.
            MenuEntry(kind="item", title="Sleep (Do Not Disturb)", action="dnd",
                      checked=self.runtime.do_not_disturb),
            MenuEntry(kind="separator"),
            # Named for what the click will do. A one-way Open would be the only
            # item in the menu that can be picked to no effect.
            MenuEntry(kind="item", title="Hide Dashboard" if panel_open else "Open Dashboard",
                      action="dashboard"),
            MenuEntry(kind="submenu", title="Skin", children=skins),
            MenuEntry(kind="separator"),
            MenuEntry(kind="item", title="Show in Menu Bar", action="menu_bar",
                      checked=self.prefs.show_menu_bar),
            MenuEntry(kind="item", title="Show in Dock", action="dock",
                      checked=self.prefs.show_dock),
            MenuEntry(kind="separator"),
            MenuEntry(kind="item", title=self.update_label, action="updates"),
            MenuEntry(kind="separator"),
            MenuEntry(kind="item", title="Quit", action="quit"),
        )

    def can_handle_menu(self, action: str) -> bool:
        """Is there a handler for this action key?

        Exists so a test can prove every action the model offers is reachable.
        An entry whose action nothing dispatches is a menu item that silently
        does nothing when picked.
        """

        if action.startswith("skin:"):
            return is_known_skin(action[len("skin:"):])
        return action in ("dnd", "dashboard", "menu_bar", "dock", "updates", "quit")

    def on_menu_action(self, action: str) -> None:
        """Apply a picked menu entry.

        Called from an Objective-C callback, so nothing here may raise: an
        exception would unwind into AppKit, which has nowhere to put it. An
        unknown action is ignored rather than trusted.
        """

        try:
            if action.startswith("skin:"):
                skin_id = action[len("skin:"):]
                if is_known_skin(skin_id):
                    self.select_skin(skin_id)
                return
            if action == "dnd":
                self.runtime.set_do_not_disturb(
                    not self.runtime.do_not_disturb, self.clock())
                self._drawn_frame = None
                self.render(self.clock())
                return
            if action == "dashboard":
                # Named for what it does, so it is never a no-op.
                if self.panel is not None and self.panel.visible:
                    self.hide_panel()
                else:
                    self.show_panel()
                return
            if action in ("menu_bar", "dock"):
                field = "show_menu_bar" if action == "menu_bar" else "show_dock"
                setattr(self.prefs, field, not getattr(self.prefs, field))
                self._save_prefs()
                self._apply_visibility()
                return
            if action == "updates":
                self.check_for_updates()
                return
            if action == "quit":
                self.quit()
        except Exception:
            # Same reasoning as the trampolines in `nswindow`: stay alive.
            pass

    def _apply_visibility(self) -> None:
        """Hook for the Dock and menu-bar work; a no-op until that unit lands."""

    def refresh_update_label(self, *, force: bool = False) -> None:
        """Refresh the update label, off the frame loop.

        Called when the menu is about to open rather than when the item is
        picked, because an NSMenu dismisses on selection and a label written
        afterwards is shown to nobody.

        The fetch runs on a worker thread for the same reason the observer
        does: a slow registry on the loop thread would freeze the animation and
        stall the heartbeat, and past the staleness window a second launch
        would decide this pet had died.
        """

        now = self.clock()
        if not force and now - self._update_checked_ms < updates.CACHE_MS:
            return
        if self._update_thread is not None and self._update_thread.is_alive():
            return  # a second menu open must not start a second fetch
        self._update_checked_ms = now

        def run() -> None:
            published = updates.fetch_published(updates.package_name())
            if published is None:
                self.update_label = updates.unreachable_label()
                return
            self.update_label = updates.label(
                updates.installed_version(), published,
                upgrade_hint=f"dsh plugin --profile web add {updates.package_name()}",
            )

        self._update_thread = threading.Thread(
            target=run, name="dsh-desk-pet-updates", daemon=True)
        self._update_thread.start()

    def check_for_updates(self) -> None:
        """Picking the item forces a refresh; the answer lands on the next open."""

        self.refresh_update_label(force=True)

    def show_panel(self) -> None:
        """Open the panel, or leave it open. Never closes it.

        Split out of `toggle_panel` because the menu needs a one-way Open:
        wiring the menu straight to the toggle would close the dashboard for
        anyone who already had it open from a left-click.
        """

        if self.window is None:
            return
        self._present_panel()

    def hide_panel(self) -> None:
        if self.panel is not None and self.panel.visible:
            self.panel.hide()

    def toggle_panel(self) -> None:
        if self.window is None:
            return
        if self.panel is not None and self.panel.visible:
            self.panel.hide()
            return
        self._present_panel()

    def _present_panel(self) -> None:
        if self.panel is None:
            self.panel = nswindow.PanelWindow()
            # Child of the pet, so AppKit moves the two together. Following the
            # pet from our own loop cannot work during a drag: AppKit's drag
            # loop owns the thread until the mouse comes up.
            self.panel.attach_to(self.window)
        rows, footer = self.panel_rows()
        if not rows:
            rows = [(False, "no DSH sessions yet", "", "")]
        origin = self._panel_origin(*self.window.position())
        self.panel.show(rows, x=origin[0], y=origin[1], footer=footer)

    def _on_moved(self, x: int, y: int) -> None:
        self.prefs.x, self.prefs.y = int(x), int(y)
        self._save_prefs()
        # The panel is anchored to the pet, so it has to travel with it.
        # Leaving it behind makes them read as two unrelated windows.
        self._reposition_panel()

    def _reposition_panel(self) -> None:
        """Re-anchor the panel after something other than a drag moved the pet.

        Dragging needs no help — the panel is a child window, so AppKit carries
        it along. This is for the cases where the pet's size changes underneath
        it, such as a skin or scale change.
        """

        if self.window is None or self.panel is None or not self.panel.visible:
            return
        x, y = self.window.position()
        self.panel.move_to(*self._panel_origin(x, y))

    def _panel_origin(self, x: int, y: int) -> tuple[int, int]:
        """Where the panel's top-left goes, given the pet's.

        Under the pet and nudged left, so a panel wider than the pet still has
        somewhere to be when the pet is near the left edge of the screen.
        """

        return max(8, x - 60), y + self.canvas_side - 8

    def _save_prefs(self) -> None:
        if not self.save_prefs:
            return
        if not prefs_store.save(self.prefs):
            # A read-only home is not worth killing the pet over; stop retrying.
            self.save_prefs = False

    def _publish(self, at_ms: int) -> None:
        """Write skin/state to disk for anything asking from outside.

        On change, and otherwise on a heartbeat: a second launch decides whether
        a pet is already running by how fresh this file is, so a pet that sat in one
        state for a minute must not look like a pet that died a minute ago.
        """

        if not self.publish_state:
            return
        current = (self.painted_skin, self.painted_state)
        if current == self._published and at_ms - self._published_at_ms < HEARTBEAT_MS:
            return
        try:
            bridge.publish(self.painted_skin, self.painted_state, epoch_ms=at_ms)
        except OSError:
            self.publish_state = False
            return
        self._published = current
        self._published_at_ms = at_ms

    # -------------------------------------------------------------- drawing

    def render(self, at_ms: int) -> None:
        """Show the frame this instant calls for, at the offset motion calls for."""

        self.painted_skin = self.runtime.skin_id
        self.painted_state = self.runtime.state
        self._publish(at_ms)

        loop = packs.loop_for(self.runtime.skin_id, self.runtime.state, web=True)
        frame = loop.frame_at(self.runtime.state_elapsed_ms(at_ms))
        self.painted_frame = frame
        if self.window is None or frame is None:
            return
        if frame != self._drawn_frame:
            self.window.set_image(frame)
            self._drawn_frame = frame

    def _user_idle_ms(self, at_ms: int) -> int | None:
        """How long the pointer has sat still, anywhere on screen.

        Dozing needs both clocks: an agent with nothing to do is not the same
        thing as a desk with nobody at it, and only the second should put the
        pet to sleep. Sampled rather than read every frame — the threshold is
        ninety seconds, so sub-second precision buys nothing.
        """

        if self.window is None:
            return None
        if at_ms - self._pointer_checked_ms < POINTER_MS:
            return at_ms - self._pointer_moved_ms
        self._pointer_checked_ms = at_ms
        position = self.window.pointer()
        if position is None:
            return None
        if position != self._pointer_seen:
            self._pointer_seen = position
            self._pointer_moved_ms = at_ms
        return at_ms - self._pointer_moved_ms

    def _motion(self, at_ms: int):
        # The *requested* state, not the resolved one. A state with no art yet
        # borrows idle's frames, and borrowing idle's breath too would leave
        # nothing at all to tell them apart.
        return motion_for(
            self.runtime.state,
            self.runtime.state_elapsed_ms(at_ms),
            half_width=self.canvas_side / 2,
            hop_until_ms=self.runtime.hop_until_ms,
            now_ms=at_ms,
        )

    # ----------------------------------------------------------------- loops

    def _start_watcher(self) -> None:
        """Observe DSH on a background thread, not on the one drawing frames.

        `observe_activity` can walk the sessions tree and shell out to `ps`.
        Doing that inline would stall the frame loop for as long as it takes.
        """

        def loop() -> None:
            while not self._stop_watch.is_set():
                try:
                    self._latest_activity = observe_activity()
                except Exception as exc:
                    if DEBUG:
                        print(f"[watch] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                    self._latest_activity = None
                self._stop_watch.wait(POLL_MS / 1000)

        if self._watcher is not None:
            return
        self._watcher = threading.Thread(target=loop, name="dsh-desk-pet-observer", daemon=True)
        self._watcher.start()

    def quit(self) -> None:
        self._running = False
        self._stop_watch.set()
        if self.panel is not None:
            self.panel.close()
            self.panel = None
        if self.window is not None:
            self.window.close()
            self.window = None
        if self.publish_state:
            # Otherwise the next launch reads a fresh-looking file and refuses
            # to start, believing this pet is still alive.
            try:
                bridge.clear()
            except OSError:
                pass

    def build(self) -> None:
        side = self.canvas_side
        x = self.prefs.x if self.prefs.x is not None else 120
        y = self.prefs.y if self.prefs.y is not None else 160
        self.window = nswindow.PetWindow(
            side, side, x=x, y=y,
            on_click=self._on_click,
            on_moved=self._on_moved,
            on_menu=self.next_skin,
            hit_test=self.is_on_pet,
        )
        self.render(self.clock())

    def install_signal_handlers(self) -> None:
        """Leave on SIGTERM the same way a menu Quit does.

        `--stop` and the host plugin's teardown both send SIGTERM, which by
        default kills the process outright — so `quit` never runs, the state
        file is never cleared, and the next launch reads a file that still
        looks fresh and refuses to start until the staleness window passes.

        Only ever installed on the main thread, and never in a test.
        """

        def leave(_signum, _frame):
            self._running = False

        for name in ("SIGTERM", "SIGINT"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                signal.signal(number, leave)
            except (ValueError, OSError):
                # Not the main thread, or a platform without it. The loop still
                # exits on its own conditions.
                pass

    def run(self) -> int:
        self.build()
        self.install_signal_handlers()
        self._start_watcher()
        self._running = True
        last_poll = 0
        try:
            while self._running:
                at = self.clock()
                try:
                    self.runtime.tick(at, self._user_idle_ms(at))
                    if at - last_poll >= POLL_MS:
                        last_poll = at
                        activity = self._latest_activity
                        if DEBUG:
                            print(f"[poll] observed={activity} state={self.runtime.state}",
                                  file=sys.stderr, flush=True)
                        if activity is not None:
                            self.runtime.apply_activity(activity, at)
                    if at - self._topmost_at_ms >= TOPMOST_MS and self.window is not None:
                        self._topmost_at_ms = at
                        self.window.float_above_fullscreen()
                    self.render(at)
                except Exception as exc:
                    # One bad frame must never end the loop. The pet going
                    # still while the process lives is the worst failure mode:
                    # it looks alive and has stopped listening.
                    if DEBUG:
                        print(f"[tick] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                if self.window is None:
                    break
                self.window.pump(FRAME_MS / 1000)
        except KeyboardInterrupt:
            pass
        finally:
            self.quit()
        return 0

    # ------------------------------------------------------------------ probe

    def probe(self, probe_skin: str = "threadcore") -> int:
        """Report what the pet would paint, without opening a window.

        Everything here is renderer-independent, which is what keeps it
        runnable in CI and under a sandbox.
        """

        base = self.clock()
        self.render(base)
        print(f"WINDOW={self.canvas_side}x{self.canvas_side}")
        print(f"RENDERER={'appkit' if nswindow.available() else 'unavailable'}")
        print(f"DEFAULT_SKIN={self.painted_skin}")
        print(f"STATE={self.painted_state}")
        print(f"FRAME={self.painted_frame.name if self.painted_frame else 'none'}")

        seen = set()
        for offset in range(0, 3200, 80):
            self.render(base + offset)
            if self.painted_frame:
                seen.add(self.painted_frame.name)
        print(f"IDLE_DISTINCT_FRAMES={len(seen)}")

        before = self.runtime.state
        after = self.select_skin(probe_skin)
        print(f"SKIN_AFTER={self.painted_skin}")
        print(f"STATE_UNCHANGED={1 if after == before else 0}")

        inventory = packs.pack_inventory(web=True)
        missing = [
            f"{skin}/{state}"
            for skin, states in inventory.items()
            for state, count in states.items()
            if count == 0 and state in ("idle", "working", "waiting", "error")
        ]
        print(f"PACK_SKINS={len(inventory)}")
        print(f"MISSING_CORE_PACKS={','.join(missing) if missing else 'none'}")

        ok = self.painted_skin == probe_skin and len(seen) >= 2 and not missing
        return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Always-on-top DSH desktop pet")
    parser.add_argument("--probe", action="store_true", help="print diagnostics without a window")
    parser.add_argument("--probe-skin", default="threadcore", help="skin the probe switches to")
    parser.add_argument("--skin", help="starting skin id (overrides the saved one)")
    parser.add_argument("--state", default="idle", help="starting state")
    parser.add_argument("--scale", type=float, help="size multiplier, e.g. 0.7")
    parser.add_argument("--small", action="store_true", help="shorthand for --scale 0.5")
    parser.add_argument("--reset", action="store_true", help="forget saved position, size and skin")
    parser.add_argument("--inventory", action="store_true", help="print the frame inventory and exit")
    parser.add_argument("--allow-second", action="store_true", help="start even if a pet is running")
    args = parser.parse_args(argv)

    if args.inventory:
        for skin, states in packs.pack_inventory(web=True).items():
            counts = " ".join(f"{state}={count}" for state, count in states.items())
            print(f"{skin:12s} {counts}")
        return 0

    saved = prefs_store.Prefs() if args.reset else prefs_store.load()
    if args.skin:
        get_skin(args.skin)
        saved.skin_id = args.skin
    if args.small:
        saved.scale = 0.5
    if args.scale:
        saved.scale = args.scale
    saved = saved.clamped()

    runtime = PetRuntime(skin_id=saved.skin_id, state=args.state, now_ms=now_ms())  # type: ignore[arg-type]
    app = DeskPetApp(runtime, prefs=saved)

    if args.probe:
        app.publish_state = False
        app.save_prefs = False
        return app.probe(args.probe_skin)

    if not args.allow_second:
        running = bridge.live_pid()
        if running is not None:
            # Every DSH profile launches the plugin, so a second profile would
            # otherwise put a second pet on screen, both writing the same state
            # file and the page showing whichever wrote last.
            print(f"a desk pet is already running (pid {running}); use --allow-second to override")
            return 3

    return app.run()


if __name__ == "__main__":
    sys.exit(main())
