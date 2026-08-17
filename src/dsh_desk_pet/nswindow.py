"""The pet's window, built directly on AppKit through ctypes.

Tk was the obvious choice and turned out to be unusable. macOS ships Tcl/Tk
8.5.9 — released in 2010 — and on macOS 26 its Aqua drawing path no longer
reaches the screen: the window maps, the canvas reports itself mapped, viewable,
correctly sized and holding an image at the right coordinates, and what appears
is an empty system-grey rectangle. Nothing above that layer can fix it.

So the window is AppKit's, driven straight through `objc_msgSend`. That is a lot
of machinery to write by hand, and it buys three things Tk could not give at
all:

* **Real alpha.** Tk 8.5's `PhotoImage` reads GIF and nothing else, so the
  desktop pet was limited to a 1-bit matte. `NSImage` takes the RGBA PNGs the
  build already produces, with the soft edges intact.
* **Window level and Spaces.** The pet can sit above fullscreen apps, which a
  boolean always-on-top cannot do.
* **Per-pixel hit testing**, so clicks on empty corners fall through to whatever
  is underneath instead of being swallowed by a rectangle.

Still no third-party dependencies: `ctypes` is standard library, and the system
Python is the only requirement.

The one genuinely awkward part is receiving mouse events, which needs a real
Objective-C subclass. `objc_allocateClassPair` plus `class_addMethod` with
ctypes callbacks does it; the callbacks must outlive the class, hence `_KEEP`.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import time
from pathlib import Path
from typing import Callable

# NSWindowCollectionBehavior bits.
CAN_JOIN_ALL_SPACES = 1 << 0
STATIONARY = 1 << 4
FULLSCREEN_AUXILIARY = 1 << 8
# The level assistive software uses; above the fullscreen content layer.
ASSISTIVE_TECH_HIGH_LEVEL = 1500

NSWindowStyleMaskBorderless = 0
NSBackingStoreBuffered = 2
NSApplicationActivationPolicyAccessory = 1

# Anything the runtime must not garbage-collect: ctypes callbacks handed to the
# Objective-C runtime, and the images currently on screen.
_KEEP: list = []


class NSRect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("w", ctypes.c_double),
        ("h", ctypes.c_double),
    ]


class NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Runtime:
    """Thin, typed access to the bits of the Objective-C runtime we use."""

    def __init__(self) -> None:
        self.objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        for framework in ("AppKit", "Foundation", "QuartzCore"):
            path = ctypes.util.find_library(framework)
            if path:
                ctypes.cdll.LoadLibrary(path)

        self.objc.objc_getClass.restype = ctypes.c_void_p
        self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self.objc.sel_registerName.restype = ctypes.c_void_p
        self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self.objc.objc_allocateClassPair.restype = ctypes.c_void_p
        self.objc.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self.objc.objc_registerClassPair.restype = None
        self.objc.objc_registerClassPair.argtypes = [ctypes.c_void_p]
        self.objc.class_addMethod.restype = ctypes.c_bool
        self.objc.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]

        # objc_msgSend is variadic, so every distinct signature needs its own
        # CFUNCTYPE built from the symbol's address. Reusing one handle and
        # reassigning argtypes silently corrupts arguments rather than failing.
        self._addr = ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value

    def sig(self, restype, *argtypes):
        return ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(self._addr)

    def cls(self, name: str):
        return self.objc.objc_getClass(name.encode())

    def sel(self, name: str):
        return self.objc.sel_registerName(name.encode())


class PetWindow:
    """A borderless, transparent, always-on-top window showing one image.

    Callbacks are plain Python functions:

    * ``on_click()``   — pressed and released without moving
    * ``on_moved(x,y)``— finished a drag, in screen coordinates
    * ``on_menu()``    — right-clicked (or control-clicked)
    * ``hit_test(x,y)``— is this point on the character? Coordinates are
      top-left origin, so they match how the frames were authored. Returning
      False makes the click fall through to whatever is behind the window.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        x: int = 120,
        y: int = 160,
        on_click: Callable[[], None] | None = None,
        on_moved: Callable[[int, int], None] | None = None,
        on_menu: Callable[[], None] | None = None,
        hit_test: Callable[[float, float], bool] | None = None,
    ) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("the desk pet window is macOS-only")

        self.rt = rt = _Runtime()
        self.width, self.height = width, height
        self.on_click = on_click
        self.on_moved = on_moved
        self.on_menu = on_menu
        self.hit_test = hit_test
        self._images: dict[Path, int] = {}
        self._closed = False
        self._pressed = False
        self._moved = False

        self._ptr = rt.sig(ctypes.c_void_p)
        self._ptr_ptr = rt.sig(ctypes.c_void_p, ctypes.c_void_p)
        self._void_ptr = rt.sig(None, ctypes.c_void_p)
        self._void_bool = rt.sig(None, ctypes.c_bool)
        self._void_long = rt.sig(None, ctypes.c_long)
        self._void_ulong = rt.sig(None, ctypes.c_ulong)
        self._double = rt.sig(ctypes.c_double)
        self._rect = rt.sig(NSRect)
        self._void_point = rt.sig(None, NSPoint)
        self._init_rect = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, NSRect
        )(rt._addr)
        self._init_window = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            NSRect, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool,
        )(rt._addr)

        app = self._ptr(rt.cls("NSApplication"), rt.sel("sharedApplication"))
        # Accessory: no Dock icon, no menu bar. It is a pet, not an app.
        self._void_long(app, rt.sel("setActivationPolicy:"), NSApplicationActivationPolicyAccessory)
        self._app = app

        screen_h = self._screen_height()
        # AppKit's origin is bottom-left; every coordinate the rest of this
        # project uses is top-left, so conversion happens here and nowhere else.
        frame = NSRect(x, screen_h - y - height, width, height)
        window = self._ptr(rt.cls("NSWindow"), rt.sel("alloc"))
        window = self._init_window(
            window, rt.sel("initWithContentRect:styleMask:backing:defer:"),
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False,
        )
        self._void_bool(window, rt.sel("setOpaque:"), False)
        self._ptr_ptr(window, rt.sel("setBackgroundColor:"),
                      self._ptr(rt.cls("NSColor"), rt.sel("clearColor")))
        self._void_bool(window, rt.sel("setHasShadow:"), False)
        self._void_bool(window, rt.sel("setIgnoresMouseEvents:"), False)
        self._window = window
        self.float_above_fullscreen()

        view_class = self._make_view_class()
        view = self._init_rect(
            self._ptr(view_class, rt.sel("alloc")), rt.sel("initWithFrame:"),
            NSRect(0, 0, width, height),
        )
        self._void_bool(view, rt.sel("setWantsLayer:"), True)
        self._view = view
        self._layer = self._ptr(view, rt.sel("layer"))
        self._ptr_ptr(self._layer, rt.sel("setContentsGravity:"), self._nsstring("resizeAspect"))
        self._ptr_ptr(window, rt.sel("setContentView:"), view)
        self._ptr_ptr(window, rt.sel("orderFront:"), None)

    # ------------------------------------------------------------- internals

    def _nsstring(self, text: str):
        return self._ptr_ptr(
            self.rt.cls("NSString"), self.rt.sel("stringWithUTF8String:"),
            ctypes.cast(ctypes.c_char_p(text.encode()), ctypes.c_void_p),
        )

    def _screen_height(self) -> float:
        rt = self.rt
        screen = self._ptr(rt.cls("NSScreen"), rt.sel("mainScreen"))
        if not screen:
            return 1080.0
        return self._rect(screen, rt.sel("frame")).h

    def _make_view_class(self):
        """Subclass NSView so the window can hear the mouse.

        AppKit only delivers mouse events to a view that implements the
        handlers, and `movableByWindowBackground` is not enough: an
        `NSImageView` swallows the press without moving anything, which is how
        the first prototype ended up visible but undraggable.
        """

        rt = self.rt
        name = f"DshPetView{id(self)}".encode()
        view_class = rt.objc.objc_allocateClassPair(rt.cls("NSView"), name, 0)

        def _down(_self, _cmd, event):
            self._pressed = True
            self._moved = False

        def _dragged(_self, _cmd, event):
            self._pressed = True
            self._moved = True
            dx = self._double(event, rt.sel("deltaX"))
            dy = self._double(event, rt.sel("deltaY"))
            frame = self._rect(self._window, rt.sel("frame"))
            # deltaY grows downward in event space and upward in screen space.
            self._void_point(self._window, rt.sel("setFrameOrigin:"),
                             NSPoint(frame.x + dx, frame.y - dy))

        def _up(_self, _cmd, event):
            was_drag, self._pressed = self._moved, False
            if was_drag:
                if self.on_moved:
                    x, y = self.position()
                    self.on_moved(x, y)
            elif self.on_click:
                self.on_click()

        def _right(_self, _cmd, event):
            if self.on_menu:
                self.on_menu()

        def _hit(_self, _cmd, point: NSPoint):
            """Per-pixel click-through: the one thing Tk could not do at all.

            AppKit asks the view which point it wants; answering nil for a
            transparent pixel lets the click reach the desktop behind the pet,
            so the window stops being an invisible rectangle that eats clicks.
            """

            if self.hit_test is None:
                return self._view
            local = point
            try:
                # Convert screen-ish window coords to top-left view coords.
                if self.hit_test(local.x, self.height - local.y):
                    return self._view
            except Exception:
                return self._view
            return None

        signatures = [
            ("mouseDown:", _down, b"v@:@", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
            ("mouseDragged:", _dragged, b"v@:@", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
            ("mouseUp:", _up, b"v@:@", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
            ("rightMouseDown:", _right, b"v@:@", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
            ("hitTest:", _hit, b"@@:{CGPoint=dd}", ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, NSPoint)),
        ]
        for selector, fn, types, proto in signatures:
            imp = proto(fn)
            _KEEP.append(imp)
            rt.objc.class_addMethod(view_class, rt.sel(selector), ctypes.cast(imp, ctypes.c_void_p), types)

        rt.objc.objc_registerClassPair(view_class)
        return view_class

    # ----------------------------------------------------------------- public

    def set_image(self, path: Path) -> None:
        """Show this frame. Images are cached; NSImage decode is not free."""

        if self._closed:
            return
        image = self._images.get(path)
        if image is None:
            image = self._ptr_ptr(
                self._ptr(self.rt.cls("NSImage"), self.rt.sel("alloc")),
                self.rt.sel("initWithContentsOfFile:"), self._nsstring(str(path)),
            )
            if not image:
                return
            self._images[path] = image
            _KEEP.append(image)
        self._ptr_ptr(self._layer, self.rt.sel("setContents:"), image)

    def position(self) -> tuple[int, int]:
        """Top-left of the window in screen coordinates, y growing downward."""

        frame = self._rect(self._window, self.rt.sel("frame"))
        return int(frame.x), int(self._screen_height() - frame.y - frame.h)

    def move_to(self, x: int, y: int) -> None:
        screen_h = self._screen_height()
        self._void_point(self._window, self.rt.sel("setFrameOrigin:"),
                         NSPoint(x, screen_h - y - self.height))

    def float_above_fullscreen(self) -> None:
        """Raise above ordinary windows *and* onto every Space.

        Level alone is not enough: a fullscreen application owns its own Space,
        and a window that has not joined all Spaces simply is not in it.
        """

        self._void_long(self._window, self.rt.sel("setLevel:"), ASSISTIVE_TECH_HIGH_LEVEL)
        self._void_ulong(self._window, self.rt.sel("setCollectionBehavior:"),
                         CAN_JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUXILIARY)

    def pump(self, seconds: float) -> None:
        """Let AppKit deliver events for a while. This is the frame tick."""

        if self._closed:
            time.sleep(seconds)
            return
        rt = self.rt
        loop = self._ptr(rt.cls("NSRunLoop"), rt.sel("currentRunLoop"))
        date_after = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double
        )(rt._addr)
        run_until = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(rt._addr)
        until = date_after(rt.cls("NSDate"), rt.sel("dateWithTimeIntervalSinceNow:"), seconds)
        run_until(loop, rt.sel("runMode:beforeDate:"), self._nsstring("kCFRunLoopDefaultMode"), until)

    def pointer(self) -> tuple[float, float] | None:
        """Global pointer position, or None if AppKit will not say.

        Global rather than pointer-events-over-our-window, because the question
        it answers is "is anyone at this desk", not "is anyone hovering the
        pet". It is what stops the pet dozing off while you are working in
        another app.
        """

        try:
            point = self.rt.sig(NSPoint)(self.rt.cls("NSEvent"), self.rt.sel("mouseLocation"))
            return point.x, point.y
        except Exception:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._ptr_ptr(self._window, self.rt.sel("orderOut:"), None)
        except Exception:
            pass


def available() -> bool:
    """Can this machine host the window at all?"""

    if sys.platform != "darwin":
        return False
    try:
        return bool(_Runtime().cls("NSWindow"))
    except Exception:
        return False
