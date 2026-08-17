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
    * ``on_drag_start()`` — a drag just began; `dragging` stays True until it ends
    * ``hit_test(x,y)``— is this point on the character? Accepted and stored,
      but not wired to AppKit yet: see `_make_view_class` on why overriding
      `hitTest:` was backed out.
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
        on_drag_start: Callable[[], None] | None = None,
    ) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("the desk pet window is macOS-only")

        self.rt = rt = _Runtime()
        self.width, self.height = width, height
        self.on_click = on_click
        self.on_moved = on_moved
        self.on_menu = on_menu
        self.hit_test = hit_test
        self.on_drag_start = on_drag_start
        # True while AppKit's drag loop owns the mouse. `performWindowDragWithEvent:`
        # does not return until the button comes up, so anything that needs to
        # keep up with the window during a drag has to watch this rather than
        # wait for the callback.
        self.dragging = False
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
        self._date_after = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double
        )(rt._addr)
        self._next_event = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool,
        )(rt._addr)
        self._launched = False

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

        Dragging goes through `performWindowDragWithEvent:` rather than adding up
        `deltaX`/`deltaY` by hand. AppKit's own implementation runs its own event
        loop until the mouse comes up, and gets the things hand-rolled dragging
        gets wrong: multiple displays, Spaces, and the tracking staying attached
        when the pointer outruns the redraw. Because it only returns once the
        drag is over, comparing the window's position across the call is also
        the cleanest way to tell a drag from a click.

        `hitTest:` is deliberately *not* overridden. Getting its struct
        argument's type encoding wrong on arm64 does not fail loudly — it
        delivers garbage coordinates, the view claims no points at all, and the
        pet becomes completely inert while still looking perfect. Click-through
        is worth having, but not at the cost of the pet responding to nothing.
        """

        rt = self.rt
        name = f"DshPetView{id(self)}".encode()
        view_class = rt.objc.objc_allocateClassPair(rt.cls("NSView"), name, 0)
        drag_with_event = rt.sig(None, ctypes.c_void_p)

        def _down(_self, _cmd, event):
            try:
                before = self.position()
                self.dragging = True
                if self.on_drag_start:
                    self.on_drag_start()
                try:
                    drag_with_event(self._window, rt.sel("performWindowDragWithEvent:"), event)
                finally:
                    self.dragging = False
                after = self.position()
                if before != after:
                    if self.on_moved:
                        self.on_moved(*after)
                elif self.on_click:
                    self.on_click()
            except Exception:
                # A raise inside an Objective-C callback unwinds into AppKit,
                # which has no idea what to do with it. Swallow and stay alive.
                self.dragging = False

        def _right(_self, _cmd, event):
            try:
                if self.on_menu:
                    self.on_menu()
            except Exception:
                pass

        def _accepts_first_mouse(_self, _cmd, _event):
            """Yes — and without this the pet cannot be clicked at all.

            The app is an accessory (no Dock icon, never activated), so every
            click on its window is a "first mouse". AppKit's default is to
            consume that click to activate the application and deliver nothing,
            and since this app never becomes active, *every* click is the first
            one. The pet looked perfect and ignored the mouse completely.
            """

            return True

        void_id = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        bool_id = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        methods = (
            ("mouseDown:", _down, b"v@:@", void_id),
            ("rightMouseDown:", _right, b"v@:@", void_id),
            ("acceptsFirstMouse:", _accepts_first_mouse, b"B@:@", bool_id),
        )
        for selector, fn, types, proto in methods:
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
        """Deliver AppKit events for a while. This is the frame tick.

        Through `NSApplication`, not `NSRunLoop`. Running the run loop alone
        services its sources — which is enough for Core Animation, so the pet
        *drew* perfectly — but NSEvents are dispatched to windows by
        `nextEventMatchingMask:` and `sendEvent:`, and without those the mouse
        is never delivered to anything. That is why the pet looked finished and
        could not be dragged or clicked.
        """

        if self._closed:
            time.sleep(seconds)
            return
        rt = self.rt
        if not self._launched:
            # Required before manually pumping: it finishes the parts of
            # startup that -[NSApplication run] would otherwise do.
            self._void_ptr(self._app, rt.sel("finishLaunching"), None)
            self._launched = True

        until = self._date_after(
            rt.cls("NSDate"), rt.sel("dateWithTimeIntervalSinceNow:"), seconds
        )
        event = self._next_event(
            self._app, rt.sel("nextEventMatchingMask:untilDate:inMode:dequeue:"),
            ctypes.c_ulong(0xFFFFFFFFFFFFFFFF), until,
            self._nsstring("kCFRunLoopDefaultMode"), True,
        )
        while event:
            self._ptr_ptr(self._app, rt.sel("sendEvent:"), event)
            # Drain anything else already queued, without waiting for more.
            now = self._date_after(rt.cls("NSDate"), rt.sel("dateWithTimeIntervalSinceNow:"), 0.0)
            event = self._next_event(
                self._app, rt.sel("nextEventMatchingMask:untilDate:inMode:dequeue:"),
                ctypes.c_ulong(0xFFFFFFFFFFFFFFFF), now,
                self._nsstring("kCFRunLoopDefaultMode"), True,
            )

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


class PanelWindow:
    """A small dark rounded panel of text rows, shown under the pet.

    Built from AppKit text layers rather than drawn by hand: `CATextLayer`
    renders and lays out a string, which is the whole job, and going through
    `NSAttributedString` would need a lot more type encodings to get wrong.

    Rows are plain data — `(dot, title, badge, age)` — so what the panel shows
    is decided by `sessions` and tested without a display.
    """

    ROW_HEIGHT = 30
    PADDING = 12
    CORNER = 14

    def __init__(self, width: int = 300) -> None:
        self.rt = rt = _Runtime()
        self.width = width
        self._closed = False
        self._visible = False
        self._layers: list = []
        self._parent = None

        self._ptr = rt.sig(ctypes.c_void_p)
        self._ptr_ptr = rt.sig(ctypes.c_void_p, ctypes.c_void_p)
        self._void_ptr = rt.sig(None, ctypes.c_void_p)
        self._void_bool = rt.sig(None, ctypes.c_bool)
        self._void_long = rt.sig(None, ctypes.c_long)
        self._void_ulong = rt.sig(None, ctypes.c_ulong)
        self._void_double = rt.sig(None, ctypes.c_double)
        self._void_rect = rt.sig(None, NSRect)
        self._void_point = rt.sig(None, NSPoint)
        self._rect = rt.sig(NSRect)
        self._init_rect = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, NSRect
        )(rt._addr)
        self._init_window = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            NSRect, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool,
        )(rt._addr)
        self._color = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double,
        )(rt._addr)
        self._font = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double
        )(rt._addr)

        window = self._ptr(rt.cls("NSWindow"), rt.sel("alloc"))
        window = self._init_window(
            window, rt.sel("initWithContentRect:styleMask:backing:defer:"),
            NSRect(0, 0, width, 100), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False,
        )
        self._void_bool(window, rt.sel("setOpaque:"), False)
        self._ptr_ptr(window, rt.sel("setBackgroundColor:"),
                      self._ptr(rt.cls("NSColor"), rt.sel("clearColor")))
        self._void_bool(window, rt.sel("setHasShadow:"), True)
        # Just under the pet, so the pet is never hidden by its own panel.
        self._void_long(window, rt.sel("setLevel:"), ASSISTIVE_TECH_HIGH_LEVEL - 1)
        self._void_ulong(window, rt.sel("setCollectionBehavior:"),
                         CAN_JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUXILIARY)
        self._void_bool(window, rt.sel("setIgnoresMouseEvents:"), True)
        self._window = window

        view = self._init_rect(
            self._ptr(rt.cls("NSView"), rt.sel("alloc")), rt.sel("initWithFrame:"),
            NSRect(0, 0, width, 100),
        )
        self._void_bool(view, rt.sel("setWantsLayer:"), True)
        self._ptr_ptr(window, rt.sel("setContentView:"), view)
        self._view = view
        self._root_layer = self._ptr(view, rt.sel("layer"))
        self._void_double(self._root_layer, rt.sel("setCornerRadius:"), float(self.CORNER))
        self._ptr_ptr(self._root_layer, rt.sel("setBackgroundColor:"), self._cg_color(0.09, 0.09, 0.11, 0.94))

    def _nsstring(self, text: str):
        return self._ptr_ptr(
            self.rt.cls("NSString"), self.rt.sel("stringWithUTF8String:"),
            ctypes.cast(ctypes.c_char_p(text.encode("utf-8")), ctypes.c_void_p),
        )

    def _cg_color(self, r: float, g: float, b: float, a: float):
        colour = self._color(
            self.rt.cls("NSColor"), self.rt.sel("colorWithSRGBRed:green:blue:alpha:"), r, g, b, a
        )
        return self._ptr(colour, self.rt.sel("CGColor"))

    def _text_layer(self, text: str, x: float, y: float, w: float, size: float, colour, *, bold=False):
        rt = self.rt
        layer = self._ptr(self._ptr(rt.cls("CATextLayer"), rt.sel("alloc")), rt.sel("init"))
        self._ptr_ptr(layer, rt.sel("setString:"), self._nsstring(text))
        font_name = "HelveticaNeue-Bold" if bold else "HelveticaNeue"
        font = self._font(rt.cls("NSFont"), rt.sel("fontWithName:size:"), self._nsstring(font_name), size)
        if font:
            self._ptr_ptr(layer, rt.sel("setFont:"), font)
        self._void_double(layer, rt.sel("setFontSize:"), size)
        self._ptr_ptr(layer, rt.sel("setForegroundColor:"), colour)
        self._void_double(layer, rt.sel("setContentsScale:"), 2.0)
        self._void_rect(layer, rt.sel("setFrame:"), NSRect(x, y, w, size + 6))
        return layer

    def show(self, rows: list[tuple[bool, str, str, str]], *, x: int, y: int, footer: str = "") -> None:
        """Draw these rows and place the panel with its top-left at (x, y)."""

        if self._closed:
            return
        rt = self.rt
        for layer in self._layers:
            self._void_ptr(layer, rt.sel("removeFromSuperlayer"), None)
        self._layers = []

        count = len(rows) + (1 if footer else 0)
        height = self.PADDING * 2 + max(1, count) * self.ROW_HEIGHT
        screen_h = self._rect(self._ptr(rt.cls("NSScreen"), rt.sel("mainScreen")), rt.sel("frame")).h
        self._void_rect(self._window, rt.sel("setFrame:display:"),
                        NSRect(x, screen_h - y - height, self.width, height))
        self._void_rect(self._view, rt.sel("setFrame:"), NSRect(0, 0, self.width, height))

        white = self._cg_color(0.94, 0.94, 0.96, 1.0)
        grey = self._cg_color(0.62, 0.62, 0.68, 1.0)
        green = self._cg_color(0.25, 0.80, 0.45, 1.0)
        dim = self._cg_color(0.42, 0.42, 0.48, 1.0)

        # Layers are positioned bottom-up in AppKit, so the first row is drawn
        # highest.
        top = height - self.PADDING
        for index, (active, title, badge, age) in enumerate(rows):
            row_y = top - (index + 1) * self.ROW_HEIGHT + 6
            dot = self._ptr(self._ptr(rt.cls("CALayer"), rt.sel("alloc")), rt.sel("init"))
            self._void_rect(dot, rt.sel("setFrame:"), NSRect(self.PADDING, row_y + 6, 8, 8))
            self._void_double(dot, rt.sel("setCornerRadius:"), 4.0)
            self._ptr_ptr(dot, rt.sel("setBackgroundColor:"), green if active else dim)
            self._ptr_ptr(self._root_layer, rt.sel("addSublayer:"), dot)
            self._layers.append(dot)

            title_layer = self._text_layer(title, self.PADDING + 18, row_y, self.width - 150, 13, white)
            self._ptr_ptr(self._root_layer, rt.sel("addSublayer:"), title_layer)
            self._layers.append(title_layer)

            if badge:
                badge_layer = self._text_layer(
                    badge, self.width - 128, row_y, 60, 11, green if active else grey, bold=True
                )
                self._ptr_ptr(self._root_layer, rt.sel("addSublayer:"), badge_layer)
                self._layers.append(badge_layer)

            age_layer = self._text_layer(age, self.width - 66, row_y, 56, 11, grey)
            self._ptr_ptr(self._root_layer, rt.sel("addSublayer:"), age_layer)
            self._layers.append(age_layer)

        if footer:
            footer_layer = self._text_layer(
                footer, self.PADDING + 18, self.PADDING - 2, self.width - 40, 11, grey
            )
            self._ptr_ptr(self._root_layer, rt.sel("addSublayer:"), footer_layer)
            self._layers.append(footer_layer)

        self._ptr_ptr(self._window, rt.sel("orderFront:"), None)
        self._visible = True
        self._ensure_child()

    def attach_to(self, parent: "PetWindow") -> None:
        """Remember the pet as this panel's parent, and attach to it.

        AppKit then moves the panel with the parent itself, which is the only way
        to keep them together during a drag: `performWindowDragWithEvent:` runs
        its own event loop and does not return until the mouse comes up, so no
        amount of following from our own loop can help, because our loop is not
        running.

        The parent is remembered rather than only used, because the relationship
        does not survive being hidden: see `_ensure_child`.
        """

        rt = self.rt
        try:
            add_child = rt.sig(None, ctypes.c_void_p, ctypes.c_long)
            # NSWindowAbove == 1: the panel sits over the pet's own window, but
            # its level is one below, so the pet still draws on top.
            add_child(parent._window, rt.sel("addChildWindow:ordered:"), self._window, 1)
            self._parent = parent
        except Exception:
            self._parent = None

    def _ensure_child(self) -> None:
        """Re-attach to the remembered parent, if there is one.

        `orderOut:` takes a window out of its parent's child list, so the
        relationship established once at creation was gone the moment the panel
        was closed, and every open after the first was an ordinary sibling
        window: it tracked the pet while our loop ran, then stayed behind the
        instant a drag started. Attaching on every show is what makes the two
        move as one piece however many times the panel is toggled.
        """

        if self._parent is None or self._closed:
            return
        rt = self.rt
        try:
            add_child = rt.sig(None, ctypes.c_void_p, ctypes.c_long)
            add_child(self._parent._window, rt.sel("addChildWindow:ordered:"),
                      self._window, 1)
        except Exception:
            pass

    def move_to(self, x: int, y: int) -> None:
        """Move the panel without rebuilding its rows.

        Dragging the pet re-lays-out nothing: the content has not changed, only
        where it sits, and rebuilding every layer mid-drag would show as a
        flicker under the hand.
        """

        if self._closed or not self._visible:
            return
        rt = self.rt
        frame = self._rect(self._window, rt.sel("frame"))
        screen_h = self._rect(self._ptr(rt.cls("NSScreen"), rt.sel("mainScreen")), rt.sel("frame")).h
        self._void_point(self._window, rt.sel("setFrameOrigin:"),
                         NSPoint(x, screen_h - y - frame.h))

    def hide(self) -> None:
        if self._closed or not self._visible:
            return
        self._ptr_ptr(self._window, self.rt.sel("orderOut:"), None)
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    def close(self) -> None:
        self.hide()
        self._closed = True
