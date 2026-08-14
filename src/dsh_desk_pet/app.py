"""Always-on-top draggable companion window. Not an in-page DSH plugin."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .mapper import AgentActivity
from .observer import observe_activity
from .raster import render_png, render_ppm
from .runtime import PetRuntime
from .scene import CANVAS_H, CANVAS_W
from .skins import DEFAULT_SKIN_ID, list_skins


class DeskPetApp:
    """Tk companion. Skin changes go through PetRuntime.set_skin — same as tests."""

    def __init__(self, runtime: PetRuntime | None = None) -> None:
        self.runtime = runtime or PetRuntime()
        self.painted_skin = ""
        self.painted_state = ""
        self._root = None
        self._photo = None
        self._image = None
        self._drag = (0, 0)
        self._poll_ms = 500

    def select_skin(self, skin_id: str) -> str:
        """UI entry used by the picker chips and by --probe."""

        state = self.runtime.set_skin(skin_id)
        self.redraw()
        return state

    def apply_activity(self, activity: AgentActivity | None) -> str:
        state = self.runtime.apply_activity(activity)
        self.redraw()
        return state

    def _build(self) -> None:
        import tkinter as tk

        os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
        # Force Aqua light chrome. Dark-mode Tk 8.5 leaves an empty black window
        # and never paints the canvas.
        os.environ.setdefault("NSRequiresAquaSystemAppearance", "1")
        root = tk.Tk()
        root.title("DSH Desk Pet")
        root.resizable(False, False)
        # Pin to the primary display origin. Do NOT use winfo_screenwidth():
        # on a multi-monitor Mac that is the virtual desktop union.
        root.geometry(f"{CANVAS_W}x{CANVAS_H + 40}+80+120")
        root.attributes("-topmost", True)
        root.lift()
        root.after(200, lambda: (root.lift(), root.attributes("-topmost", True)))
        try:
            root.configure(bg="#f4efe6")
            root.tk_setPalette(background="#f4efe6", foreground="#1a1a1a")
        except tk.TclError:
            pass

        image = tk.Label(root, bg="#f4efe6", bd=0)
        image.pack(side="top", fill="both", expand=True)
        image.bind("<ButtonPress-1>", self._on_press)
        image.bind("<B1-Motion>", self._on_drag)

        picker = tk.Frame(root, bg="#f4efe6")
        picker.pack(side="bottom", fill="x", pady=6)
        colors = {
            "whale": "#2f6feb",
            "threadcore": "#d9822b",
            "nautilus": "#b56b3a",
            "jellyfish": "#7c5cbf",
        }
        for skin in list_skins():
            btn = tk.Button(
                picker,
                text=" ",
                bg=colors[skin.id],
                activebackground=colors[skin.id],
                width=2,
                command=lambda skin_id=skin.id: self.select_skin(skin_id),
            )
            btn.pack(side="left", expand=True, padx=6)

        root.bind("<Escape>", lambda _event: root.destroy())
        self._root = root
        self._image = image
        self.redraw()

    def _on_press(self, event) -> None:
        if self._root is not None:
            self._drag = (event.x_root - self._root.winfo_x(), event.y_root - self._root.winfo_y())

    def _on_drag(self, event) -> None:
        if self._root is None:
            return
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self._root.geometry(f"+{x}+{y}")

    def redraw(self) -> None:
        self.painted_skin = self.runtime.skin_id
        self.painted_state = self.runtime.state
        if self._image is None:
            return
        import tkinter as tk

        ppm = render_ppm(self.runtime.skin_id, self.runtime.state)
        photo = None
        try:
            photo = tk.PhotoImage(data=ppm)
        except tk.TclError:
            cache = Path.home() / ".dsh-desk-pet"
            cache.mkdir(parents=True, exist_ok=True)
            ppm_path = cache / f"{self.runtime.skin_id}-{self.runtime.state}.ppm"
            ppm_path.write_bytes(ppm)
            try:
                photo = tk.PhotoImage(file=str(ppm_path))
            except tk.TclError:
                photo = None
        if photo is None:
            self._image.configure(text=f"{self.runtime.skin_id} / {self.runtime.state}", fg="#1a1a1a")
        else:
            self._photo = photo
            self._image.configure(image=photo)
        if self._root is not None:
            self._root.update_idletasks()

    def always_on_top(self) -> bool:
        if self._root is None:
            return False
        try:
            return bool(int(self._root.attributes("-topmost")))
        except Exception:
            return False

    def _poll(self) -> None:
        if self._root is None:
            return
        self.apply_activity(observe_activity())
        self._root.after(self._poll_ms, self._poll)

    def run(self, *, probe: bool = False, probe_skin: str = "threadcore") -> int:
        if probe:
            print("PROCESS_START=ok", flush=True)

            def _on_term(_signum, _frame) -> None:
                print("LAUNCH_ENV_FAIL=tk_create_timeout", flush=True)
                os._exit(2)

            signal.signal(signal.SIGTERM, _on_term)
            # Separate process: Tk() can spin in C without releasing the GIL.
            killer = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    f"import os,signal,time; time.sleep(6); os.kill({os.getpid()}, signal.SIGTERM)",
                ]
            )
            try:
                self._build()
            except BaseException as exc:
                print(f"LAUNCH_ENV_FAIL={type(exc).__name__}:{exc}", flush=True)
                killer.kill()
                return 2
            killer.kill()
            return self._run_probe(probe_skin)
        self._build()
        assert self._root is not None
        self._root.after(self._poll_ms, self._poll)
        self._root.mainloop()
        return 0

    def _run_probe(self, probe_skin: str) -> int:
        assert self._root is not None
        self._root.update()
        topmost = self.always_on_top()
        print(f"ALWAYS_ON_TOP={1 if topmost else 0}")
        print(f"DEFAULT_SKIN={self.painted_skin}")
        print(f"STATE={self.painted_state}")
        print(f"WINDOW={self._root.winfo_width()}x{self._root.winfo_height()}")
        before_state = self.runtime.state
        new_state = self.select_skin(probe_skin)
        self._root.update()
        print(f"SKIN_AFTER={self.painted_skin}")
        print(f"STATE_AFTER={self.painted_state}")
        print(f"STATE_UNCHANGED={1 if new_state == before_state else 0}")
        self._root.update()
        time.sleep(0.15)
        self._root.destroy()
        return 0 if topmost and self.painted_skin == probe_skin else 1


def export_png(path: Path, skin_id: str, state: str) -> None:
    path.write_bytes(render_png(skin_id, state))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Always-on-top DSH desktop pet")
    parser.add_argument("--probe", action="store_true", help="create the window, print diagnostics, exit")
    parser.add_argument("--probe-skin", default="threadcore", help="skin the probe switches to")
    parser.add_argument("--export-png", metavar="PATH", help="write a PNG of skin+state and exit")
    parser.add_argument("--skin", default=DEFAULT_SKIN_ID, help="starting skin id")
    parser.add_argument("--state", default="idle", help="starting state (idle/working/waiting/error)")
    args = parser.parse_args(argv)

    if args.export_png:
        export_png(Path(args.export_png), args.skin, args.state)
        print(f"WROTE={args.export_png} SKIN={args.skin} STATE={args.state}")
        return 0

    runtime = PetRuntime(skin_id=args.skin, state=args.state)  # type: ignore[arg-type]
    app = DeskPetApp(runtime)
    return app.run(probe=args.probe, probe_skin=args.probe_skin)


if __name__ == "__main__":
    sys.exit(main())
