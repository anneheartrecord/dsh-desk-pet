"""Reach past Tk's window API into AppKit, using only the standard library.

Tk exposes always-on-top as a boolean, which on macOS means "above ordinary
windows" and nothing more. A fullscreen application owns its own Space, and an
ordinary window — topmost or not — is simply not on that Space. That is why the
pet vanished whenever anything went fullscreen.

What actually fixes it is two AppKit properties Tk does not expose:

* **window level.** `CGAssistiveTechHighWindowLevel` (1500) sits above the
  fullscreen content layer. This is the level assistive software uses so it can
  stay visible over anything.
* **collection behaviour.** `CanJoinAllSpaces | Stationary | FullScreenAuxiliary`
  puts the window on every Space at once, including fullscreen ones, and stops
  it sliding around during Space transitions.

Reference desk pets do this through an FFI package. `ctypes` reaches the same
`objc_msgSend` with nothing installed, which matters here because the whole
plugin is meant to run on the system Python with no dependencies.

Every call is guarded. If anything about this fails — a future macOS, a Tk
built on something other than AppKit — the caller keeps the plain `-topmost`
behaviour and the pet is merely ordinary rather than broken.

Note on arm64: `objc_msgSend` is variadic, so `argtypes` and `restype` must be
declared for each distinct signature rather than reusing one handle. Getting
this wrong does not error, it corrupts arguments.
"""

from __future__ import annotations

import ctypes
import sys

# NSWindowCollectionBehavior bits, from AppKit.
CAN_JOIN_ALL_SPACES = 1 << 0
STATIONARY = 1 << 4
FULLSCREEN_AUXILIARY = 1 << 8

# The level assistive technologies use; above the fullscreen content layer.
ASSISTIVE_TECH_HIGH_LEVEL = 1500

_LIBOBJC = "/usr/lib/libobjc.A.dylib"


class _Objc:
    """Just enough of the runtime to send four messages."""

    def __init__(self) -> None:
        lib = ctypes.cdll.LoadLibrary(_LIBOBJC)

        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self._lib = lib

        # One handle per signature. Sharing a handle across signatures is the
        # classic way to get silent argument corruption on arm64.
        self._ptr = self._bind(ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p])
        self._ptr_ulong = self._bind(
            ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        )
        self._ulong = self._bind(ctypes.c_ulong, [ctypes.c_void_p, ctypes.c_void_p])
        self._void_long = self._bind(
            None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        )
        self._void_ulong = self._bind(
            None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        )

    def _bind(self, restype, argtypes):
        fn = getattr(ctypes.cdll.LoadLibrary(_LIBOBJC), "objc_msgSend")
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    def cls(self, name: str) -> int | None:
        return self._lib.objc_getClass(name.encode())

    def sel(self, name: str) -> int | None:
        return self._lib.sel_registerName(name.encode())


def _windows_of_this_app(objc: _Objc) -> list[int]:
    app_class = objc.cls("NSApplication")
    if not app_class:
        return []
    app = objc._ptr(app_class, objc.sel("sharedApplication"))
    if not app:
        return []
    windows = objc._ptr(app, objc.sel("windows"))
    if not windows:
        return []
    count = objc._ulong(windows, objc.sel("count"))
    out = []
    for index in range(int(count)):
        handle = objc._ptr_ulong(windows, objc.sel("objectAtIndex:"), index)
        if handle:
            out.append(handle)
    return out


def float_above_fullscreen() -> int:
    """Raise every window this process owns above fullscreen Spaces.

    Returns how many windows were adjusted; 0 means the technique is
    unavailable here and the caller should stay with plain always-on-top.

    Call *after* the window is mapped: an unmapped Tk window is not yet in
    `NSApplication.windows`, so there is nothing to find.
    """

    if sys.platform != "darwin":
        return 0
    try:
        objc = _Objc()
        windows = _windows_of_this_app(objc)
        if not windows:
            return 0
        behavior = CAN_JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUXILIARY
        set_level = objc.sel("setLevel:")
        set_behavior = objc.sel("setCollectionBehavior:")
        for handle in windows:
            objc._void_long(handle, set_level, ASSISTIVE_TECH_HIGH_LEVEL)
            objc._void_ulong(handle, set_behavior, behavior)
        return len(windows)
    except Exception:
        # A future macOS, a non-AppKit Tk, a hardened runtime: none of it should
        # take the pet down. Plain -topmost still works, just not over
        # fullscreen.
        return 0


def available() -> bool:
    """Can this machine do it at all? Used by the probe for reporting."""

    if sys.platform != "darwin":
        return False
    try:
        return bool(_Objc().cls("NSApplication"))
    except Exception:
        return False
