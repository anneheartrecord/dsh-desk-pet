"""The desktop window: a borderless, transparent, always-on-top companion.

Deliberately not an in-page widget. The point of this plugin is a pet that sits
*over* the DSH tab and every other window, the way the Codex pet and
claw-on-desk do, which a `<div>` in the page can never do.

Two constraints shape everything below:

* macOS ships Tk 8.5. `PhotoImage` reads GIF and nothing else — no PNG, no
  alpha channel, only a transparent palette index. `scripts/build_frames.py`
  exists to satisfy exactly that.
* A window can only be mapped where there is a window server. Under a sandbox
  or over SSH, `deiconify()` blocks forever inside C. So the window is built
  withdrawn, every risky call is guarded, and `--probe` never maps anything —
  that is what makes this file assertable in a headless test.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from . import bridge, packs, prefs as prefs_store
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
# How often to re-assert always-on-top. Aqua drops it on focus changes.
TOPMOST_MS = 4000
# Fallback plate colour if this Tk cannot do a transparent window.
OPAQUE_BG = "#f4efe6"


def now_ms() -> int:
    return int(time.monotonic() * 1000)


class DeskPetApp:
    """Tk companion. All state transitions go through PetRuntime, same as tests."""

    def __init__(
        self,
        runtime: PetRuntime | None = None,
        *,
        clock=now_ms,
        prefs: prefs_store.Prefs | None = None,
        opaque: bool = False,
    ) -> None:
        # Escape hatch. A borderless transparent window is the right look, but
        # it is also the configuration with the most ways to render as nothing
        # at all on an unfamiliar macOS build — and a pet you cannot see gives
        # you no way to tell "broken" from "invisible". `--opaque` trades the
        # look for a window that is unmistakably there.
        self.force_opaque = opaque
        self.prefs = (prefs or prefs_store.Prefs()).clamped()
        self.clock = clock
        # Seed from the same clock the app runs on. A runtime starting at t=0
        # against a monotonic clock reads its first tick as minutes of elapsed
        # idle time, and the pet launches already asleep.
        self.runtime = runtime or PetRuntime(skin_id=self.prefs.skin_id, now_ms=clock())
        self.painted_skin = ""
        self.painted_state = ""
        self.painted_frame: Path | None = None
        self.transparent = False
        self._root = None
        self._canvas = None
        self._sprite_id = None
        self._photo = None
        self._cache: dict[Path, object] = {}
        self._drag_origin: tuple[int, int] | None = None
        self._dragged = False
        self._pointer_dx: float | None = None
        self._published: tuple[str, str] | None = None
        self._published_at_ms = -HEARTBEAT_MS
        self._menu = None
        self._latest_activity: AgentActivity | None = None
        self._pointer_seen: tuple[int, int] | None = None
        self._pointer_moved_ms = 0
        self._watcher: threading.Thread | None = None
        self._stop_watch = threading.Event()
        self.publish_state = True
        self.save_prefs = True

    # ---------------------------------------------------------------- window

    @property
    def sprite_side(self) -> int:
        """Tk 8.5 can only scale a PhotoImage by whole factors, so 0.5 is the
        one alternative size available without shipping a second art pack."""

        base = packs.frame_size()
        return base // 2 if self.prefs.scale < 0.75 else base

    @property
    def canvas_side(self) -> int:
        return self.sprite_side + MARGIN * 2

    def _sprite_origin(self) -> tuple[float, float]:
        """Top-left of the sprite as currently drawn, in canvas coordinates."""

        if self._canvas is None or self._sprite_id is None:
            half = self.sprite_side / 2
            return self.canvas_side / 2 - half, self.canvas_side / 2 - half
        cx, cy = self._canvas.coords(self._sprite_id)
        return cx - self.sprite_side / 2, cy - self.sprite_side / 2

    def is_on_pet(self, x: float, y: float) -> bool:
        """Is this canvas point actually on the character, or on empty air?

        Tk cannot make a window ignore clicks per pixel, so the window is always
        a rectangle and always swallows what is under it. It can at least stop
        *itself* from reacting: dragging the pet by a corner of empty space felt
        like dragging an invisible box, which is exactly what it was.
        """

        photo = self._photo
        if photo is None:
            return True
        ox, oy = self._sprite_origin()
        px, py = int(x - ox), int(y - oy)
        if not (0 <= px < self.sprite_side and 0 <= py < self.sprite_side):
            return False
        try:
            return not bool(photo.transparency_get(px, py))
        except Exception:
            # Older Tk, or a photo without a transparency table: assume a hit
            # rather than making the pet unclickable.
            return True

    def _try(self, fn, *args, **kwargs) -> bool:
        """Run an optional Tk call; report whether this build supports it."""

        import tkinter as tk

        try:
            fn(*args, **kwargs)
            return True
        except tk.TclError:
            return False

    def _build(self, *, mapped: bool = True) -> None:
        import tkinter as tk

        os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
        root = tk.Tk()
        root.withdraw()
        root.title("DSH Desk Pet")

        side = self.canvas_side
        # Primary display origin. Never winfo_screenwidth(): on a multi-monitor
        # Mac that is the union of every display, which parks the pet off-screen.
        x = self.prefs.x if self.prefs.x is not None else 120
        y = self.prefs.y if self.prefs.y is not None else 160
        root.geometry(f"{side}x{side}+{x}+{y}")
        root.resizable(False, False)

        borderless = not self.force_opaque and self._try(root.overrideredirect, True)
        # Order matters: on Aqua, dropping the chrome clears -topmost, so it has
        # to be (re)set afterwards or the pet quietly sinks behind the browser.
        self._try(root.attributes, "-topmost", True)
        self.transparent = (
            not self.force_opaque
            and self._try(root.wm_attributes, "-transparent", True)
            and self._try(root.configure, bg="systemTransparent")
        )
        bg = "systemTransparent" if self.transparent else OPAQUE_BG
        if not self.transparent:
            self._try(root.configure, bg=OPAQUE_BG)
        if not borderless:
            # Without a title bar there is nothing to close, so only drop the
            # chrome when we actually got it.
            self._try(root.wm_attributes, "-transparent", False)

        canvas = tk.Canvas(root, width=side, height=side, highlightthickness=0, bd=0, takefocus=1)
        if not self._try(canvas.configure, bg=bg):
            self._try(canvas.configure, bg=OPAQUE_BG)
        canvas.pack(fill="both", expand=True)

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_pointer)
        canvas.bind("<Leave>", lambda _e: setattr(self, "_pointer_dx", None))
        canvas.bind("<Button-2>", self._on_menu)
        canvas.bind("<Button-3>", self._on_menu)
        canvas.bind("<Control-Button-1>", self._on_menu)

        root.bind("<Escape>", lambda _e: self.quit())
        root.bind("<q>", lambda _e: self.quit())
        # Number keys only go to 9; past that the right-click menu is the way in.
        for index, skin in enumerate(list_skins()[:9], start=1):
            root.bind(str(index), lambda _e, skin_id=skin.id: self.select_skin(skin_id))

        self._root = root
        self._canvas = canvas
        self._menu = self._build_menu(root)
        self.render(self.clock())

        if mapped:
            root.deiconify()
            root.lift()
            # Mapping the window clears -topmost on Aqua, so setting it before
            # deiconify (as the probe measures it) is not enough: measured on a
            # real display, the attribute reads back 0 once the window is up.
            # Re-assert immediately, then keep re-asserting, because focus
            # changes clear it again.
            self._topmost_tick()

    def _build_menu(self, root):
        import tkinter as tk

        menu = tk.Menu(root, tearoff=0)
        for skin in list_skins():
            menu.add_command(
                label=f"{skin.name_zh} · {skin.name}",
                command=lambda skin_id=skin.id: self.select_skin(skin_id),
            )
        menu.add_separator()
        menu.add_command(label="退出 Quit", command=self.quit)
        return menu

    def _on_menu(self, event) -> None:
        if self._menu is None:
            return
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    # ------------------------------------------------------------ interaction

    def _on_press(self, event) -> None:
        if self._root is None or not self.is_on_pet(event.x, event.y):
            return
        self._dragged = False
        self._drag_origin = (event.x_root - self._root.winfo_x(), event.y_root - self._root.winfo_y())

    def _on_drag(self, event) -> None:
        if self._root is None or self._drag_origin is None:
            return
        self._dragged = True
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self._root.geometry(f"+{x}+{y}")

    def _on_release(self, _event) -> None:
        if self._drag_origin is None:
            return  # press landed on empty air; nothing was started
        # A click that never moved is a poke, not a drag.
        if not self._dragged:
            self.runtime.poke(self.clock())
        else:
            self._remember_position()
        self._drag_origin = None

    def _remember_position(self) -> None:
        if self._root is None:
            return
        self.prefs.x = self._root.winfo_x()
        self.prefs.y = self._root.winfo_y()
        self._save_prefs()

    def _save_prefs(self) -> None:
        if not self.save_prefs:
            return
        if not prefs_store.save(self.prefs):
            # A read-only home is not worth killing the pet over; stop retrying.
            self.save_prefs = False

    def _on_pointer(self, event) -> None:
        self._pointer_dx = event.x - self.canvas_side / 2

    # ---------------------------------------------------------------- drawing

    def select_skin(self, skin_id: str) -> str:
        """Picker entry. Changing skin must never change state."""

        state = self.runtime.set_skin(skin_id)
        self.prefs.skin_id = skin_id
        self._save_prefs()
        self.render(self.clock())
        return state

    def apply_activity(self, activity: AgentActivity | None) -> str:
        state = self.runtime.apply_activity(activity, self.clock())
        self.render(self.clock())
        return state

    def _publish(self, at_ms: int) -> None:
        """Mirror skin/state to disk for the in-page overlay.

        Writes on change, and otherwise on a heartbeat: the page decides whether
        the desktop pet is alive by how fresh this file is, so a pet that sat in
        one state for a minute must not look like a pet that died a minute ago.
        """

        if not self.publish_state:
            return
        current = (self.painted_skin, self.painted_state)
        due = at_ms - self._published_at_ms >= HEARTBEAT_MS
        if current == self._published and not due:
            return
        try:
            bridge.publish(self.painted_skin, self.painted_state, epoch_ms=at_ms)
        except OSError:
            # A read-only or full home must not take the window down with it.
            self.publish_state = False
            return
        self._published = current
        self._published_at_ms = at_ms

    def _photo_for(self, path: Path):
        import tkinter as tk

        cached = self._cache.get(path)
        if cached is None:
            cached = tk.PhotoImage(file=str(path))
            if self.sprite_side != packs.frame_size():
                # subsample is nearest-neighbour and integer-only, but it is the
                # only resize Tk 8.5 offers without a second art pack.
                factor = max(1, round(packs.frame_size() / self.sprite_side))
                cached = cached.subsample(factor, factor)
            self._cache[path] = cached
        return cached

    def render(self, at_ms: int) -> None:
        """Blit the frame this instant calls for, at the offset motion calls for."""

        self.painted_skin = self.runtime.skin_id
        self.painted_state = self.runtime.state
        self._publish(at_ms)
        loop = packs.loop_for(self.runtime.skin_id, self.runtime.state)
        frame = loop.frame_at(self.runtime.state_elapsed_ms(at_ms))
        self.painted_frame = frame
        if self._canvas is None or frame is None:
            return

        motion = motion_for(
            # The *requested* state, not the resolved one. When a state has no
            # art yet it borrows idle's frames, and borrowing idle's breath too
            # would leave nothing at all to tell them apart.
            self.runtime.state,
            self.runtime.state_elapsed_ms(at_ms),
            pointer_dx=self._pointer_dx,
            half_width=self.canvas_side / 2,
            hop_until_ms=self.runtime.hop_until_ms,
            now_ms=at_ms,
        )
        centre = self.canvas_side / 2
        x, y = centre + motion.dx, centre + motion.dy

        photo = self._photo_for(frame)
        self._photo = photo
        if self._sprite_id is None:
            self._sprite_id = self._canvas.create_image(x, y, image=photo)
        else:
            self._canvas.itemconfigure(self._sprite_id, image=photo)
            self._canvas.coords(self._sprite_id, x, y)

    # ------------------------------------------------------------------ loops

    def _topmost_tick(self) -> None:
        """Keep re-asserting always-on-top.

        Aqua quietly drops the level whenever another application takes focus,
        so a single assert at startup leaves the pet sinking behind the browser
        the first time you click it. The reference desk pet runs the same
        watchdog for the same reason.
        """

        if self._root is None:
            return
        self._try(self._root.attributes, "-topmost", True)
        self._root.after(TOPMOST_MS, self._topmost_tick)

    def _user_idle_ms(self, at_ms: int) -> int | None:
        """How long the pointer has sat still, anywhere on screen.

        `winfo_pointerxy` reports the global pointer, not just pointer events
        over our own window, which is what makes this a usable proxy for "is
        anyone at this desk" rather than "is anyone hovering the pet".
        """

        if self._root is None:
            return None
        try:
            position = self._root.winfo_pointerxy()
        except Exception:
            return None
        if position != self._pointer_seen:
            self._pointer_seen = position
            self._pointer_moved_ms = at_ms
        return at_ms - self._pointer_moved_ms

    def _frame_tick(self) -> None:
        if self._root is None:
            return
        at = self.clock()
        self.runtime.tick(at, self._user_idle_ms(at))
        self.render(at)
        self._root.after(FRAME_MS, self._frame_tick)

    def _start_watcher(self) -> None:
        """Observe DSH on a background thread, not on the one drawing frames.

        `observe_activity` shells out to `ps` with a two-second timeout, walks
        the whole sessions tree and reads the newest session file. Doing that
        inline every 600ms stalls a 33ms render loop for as long as it takes,
        which shows up as the pet freezing mid-blink whenever DSH is busy.
        """

        def loop() -> None:
            while not self._stop_watch.is_set():
                try:
                    self._latest_activity = observe_activity()
                except Exception:
                    self._latest_activity = None
                self._stop_watch.wait(POLL_MS / 1000)

        if self._watcher is not None:
            return  # already watching; a second thread would just duplicate work
        self._watcher = threading.Thread(target=loop, name="dsh-desk-pet-observer", daemon=True)
        self._watcher.start()

    def _poll_tick(self) -> None:
        if self._root is None:
            return
        activity = self._latest_activity
        if activity is not None:
            self.runtime.apply_activity(activity, self.clock())
        self._root.after(POLL_MS, self._poll_tick)

    def always_on_top(self) -> bool:
        if self._root is None:
            return False
        try:
            return bool(int(self._root.attributes("-topmost")))
        except Exception:
            return False

    def quit(self) -> None:
        if self._root is not None:
            root, self._root = self._root, None
            try:
                root.destroy()
            except Exception:
                pass
        if self.publish_state:
            # Otherwise the page overlay keeps animating a pet that is gone.
            try:
                bridge.clear()
            except OSError:
                pass

    def run(self) -> int:
        self._build(mapped=True)
        assert self._root is not None
        self._start_watcher()
        self._root.after(FRAME_MS, self._frame_tick)
        self._root.after(POLL_MS, self._poll_tick)
        try:
            self._root.mainloop()
        finally:
            self._stop_watch.set()
            self.quit()
        return 0

    # ------------------------------------------------------------------ probe

    def probe(self, probe_skin: str = "threadcore") -> int:
        """Build the window without mapping it and report what it would paint.

        Never calls `deiconify`: mapping is the one Tk operation that blocks
        forever when there is no window server, and this has to stay runnable
        in CI and under a sandbox.

        Runs read-only. A diagnostic that switches skin to prove switching works
        must not leave that skin persisted — running `--probe` used to rewrite
        the user's saved skin and size, so their next real launch came up as a
        half-size threadcore for no visible reason, and `quit()` deleted the
        live pet's state file on the way out.
        """

        self.publish_state = False
        self.save_prefs = False
        self._build(mapped=False)
        assert self._root is not None
        base = self.clock()

        print(f"BORDERLESS={1 if self._root.overrideredirect() else 0}")
        print(f"TRANSPARENT={1 if self.transparent else 0}")
        print(f"ALWAYS_ON_TOP={1 if self.always_on_top() else 0}")
        print(f"WINDOW={self.canvas_side}x{self.canvas_side}")
        print(f"DEFAULT_SKIN={self.painted_skin}")
        print(f"STATE={self.painted_state}")
        print(f"FRAME={self.painted_frame.name if self.painted_frame else 'none'}")

        # Sample one idle cycle: a live pet must not paint the same frame forever.
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

        inventory = packs.pack_inventory()
        missing = [
            f"{skin}/{state}"
            for skin, states in inventory.items()
            for state, count in states.items()
            if count == 0 and state in ("idle", "working", "waiting", "error")
        ]
        print(f"PACK_SKINS={len(inventory)}")
        print(f"MISSING_CORE_PACKS={','.join(missing) if missing else 'none'}")

        ok = (
            self.painted_skin == probe_skin
            and self.always_on_top()
            and len(seen) >= 2
            and not missing
        )
        self.quit()
        return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Always-on-top DSH desktop pet")
    parser.add_argument("--probe", action="store_true", help="build without mapping, print diagnostics, exit")
    parser.add_argument("--probe-skin", default="threadcore", help="skin the probe switches to")
    parser.add_argument("--skin", help="starting skin id (overrides the saved one)")
    parser.add_argument("--state", default="idle", help="starting state")
    parser.add_argument("--small", action="store_true", help="draw at half size")
    parser.add_argument(
        "--opaque",
        action="store_true",
        help="titled window on a solid background — use if the pet is invisible",
    )
    parser.add_argument("--reset", action="store_true", help="forget saved position, size and skin")
    parser.add_argument("--inventory", action="store_true", help="print the frame inventory and exit")
    parser.add_argument(
        "--allow-second",
        action="store_true",
        help="start even if another pet is already running",
    )
    args = parser.parse_args(argv)

    if args.inventory:
        for skin, states in packs.pack_inventory().items():
            counts = " ".join(f"{state}={count}" for state, count in states.items())
            print(f"{skin:12s} {counts}")
        return 0

    if not args.probe and not args.allow_second:
        running = bridge.live_pid()
        if running is not None:
            # Every DSH profile launches the plugin, so a second profile would
            # otherwise put a second pet on screen, both writing the same state
            # file and the page showing whichever wrote last.
            print(f"a desk pet is already running (pid {running}); use --allow-second to override")
            return 0

    saved = prefs_store.Prefs() if args.reset else prefs_store.load()
    if args.skin:
        get_skin(args.skin)
        saved.skin_id = args.skin
    if args.small:
        saved.scale = 0.5
    saved = saved.clamped()

    # Seed the runtime with the same clock the app uses. Left at 0, the first
    # tick would read `state_elapsed_ms` as the whole monotonic clock — which on
    # platforms where that is boot-relative sails straight past SLEEP_AFTER_MS
    # and the pet launches already asleep.
    runtime = PetRuntime(skin_id=saved.skin_id, state=args.state, now_ms=now_ms())  # type: ignore[arg-type]
    app = DeskPetApp(runtime, prefs=saved, opaque=args.opaque)
    return app.probe(args.probe_skin) if args.probe else app.run()


if __name__ == "__main__":
    sys.exit(main())
