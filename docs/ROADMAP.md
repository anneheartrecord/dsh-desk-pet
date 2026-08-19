# Roadmap

What v1 deliberately left out, and why. Ordered by how much each one is missed
in daily use, not by how hard it is.

## Shipped in v2

Right-click opens a native menu instead of cycling skins: quiet mode, the
session list, a skin submenu, menu-bar and Dock visibility, an update check, and
quit. A shipped skill turns one image into a full skin, generated on the user's
own tool and credentials, installed outside the package so an upgrade cannot
delete it. The frame pipeline is pure standard library — no ffmpeg — which is
what let the install path exist on a user's machine at all.

## Shipped in 0.3.0

`--skin-sheet <id>` draws a skin's six states as one image, so a skin generated
from someone's photo can leave the machine that generated it. Before this the
only way to show one was a screen recording. A community gallery collects them;
the preview image is the whole submission, so nobody uploads frames.

## Still open

### Settings window

Deferred from v2 because nothing in the package has a window UI: the pet is a
200px frameless window and a panel, and a settings surface would be built from
`objc_msgSend` upwards. Everything it would hold is reachable from the menu
today, which is why it waited rather than blocked.

### Mini mode

Not a size change. The reference implementation docks to the screen edge and
swaps in a **separate eight-pose art set** — enter, peek, alert, happy, sleep,
crabwalk and two more. That is eight new poses per skin, and a skin generated
from someone's photo would have none of them, so it needs a way for a skin to
declare it does not support the mode.

### Click-through on the transparent margin

The window is a 200px square and the character does not fill it, so clicks in
the corners hit the pet instead of whatever is behind it. The fix is a
`hitTest:` override returning nil for pixels whose alpha is below a threshold.
It is written and unit-tested against the frame data; what is missing is wiring
it into the AppKit view, which needs care because `hitTest:` runs on every
mouse move and must not decode a PNG each time.

The menu makes its absence more visible: a stray right-click on the margin now
opens a seven-item menu over whatever was behind it, where before it quietly
cycled a skin. `imaging.alpha_bounds` is the precomputed-alpha groundwork this
needs; what remains is the `NSPoint`-by-value encoding the menu work
deliberately avoided.

### Transition frames

State changes cut straight from one loop to the next. Idle into sleeping is the
one that shows: the pet should visibly settle rather than blink into a doze.
This is art, not code — the timeline format already supports one-shot sequences.

### Clickable session rows

The panel lists sessions but they do not do anything. Clicking one should
attach to that session. This needs a way to talk to DSH rather than just read
its files, which is a bigger change than it looks.

### Names left over from the in-page pet

Two pieces of vestigial naming, both mechanical to fix and both currently traps:

- **`assets/web/` is what the pet renders from.** Every call into `packs` passes
  `web=True`. The name says otherwise, so "remove the web assets" would delete
  all the art. `assets/frames/` would say what it is.
- **`packs` still takes a `web` flag, defaulting to `False`** — that is,
  defaulting to the GIF tree nothing reads. Shipped code always passes `True`;
  only tests use the default.

Worth doing together with dropping GIF generation from `build_frames.py`, since
the flag exists only to choose between the two formats.

## Not planned

- **Windows and Linux.** The renderer is AppKit through `ctypes`. A port would
  be a second renderer behind the same interface, which is real work with no
  shared code, and I only run macOS.
- **Configurable animation timing.** The timelines are per-state data in
  `anim.py`. Exposing them as settings would multiply the ways the pet can look
  wrong for no gain I can name.
