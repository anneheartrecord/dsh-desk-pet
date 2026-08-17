"""The desktop pet: an AppKit window driven by the shared state machine.

Deliberately not an in-page widget. The point of this plugin is a pet that sits
*over* the DSH tab and every other window, the way the Codex pet and
claw-on-desk do, which a `<div>` in the page can never do.

This file owns the loop and nothing else. `observer` decides what DSH is doing,
`runtime` decides what the pet should therefore be, `packs` and `anim` decide
which frame that means right now, `nswindow` puts it on screen, and `bridge`
tells the in-page mirror. Each of those is testable without a display; this is
the only part that needs one.

The renderer is AppKit rather than Tk because macOS ships Tk 8.5.9 from 2010,
and on macOS 26 its drawing path no longer reaches the screen — see
`nswindow.py`. Moving to AppKit also let the desktop pet switch from the 1-bit
GIF matte to the RGBA PNGs, which is why the edges are soft now.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from . import bridge, nswindow, packs, prefs as prefs_store, sessions
from .anim import motion_for
from .mapper import AgentActivity
from .observer import observe_activity
from .runtime import PetRuntime
from .skins import DEFAULT_SKIN_ID, get_skin, list_skins

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

    def toggle_panel(self) -> None:
        if self.window is None:
            return
        if self.panel is not None and self.panel.visible:
            self.panel.hide()
            return
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
        """Mirror skin/state to disk for the in-page overlay.

        On change, and otherwise on a heartbeat: the page decides whether the
        desktop pet is alive by how fresh this file is, so a pet that sat in one
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
            # Otherwise the page overlay keeps animating a pet that is gone.
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

    def run(self) -> int:
        self.build()
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
