# Roadmap

What v1 deliberately left out, and why. Ordered by how much each one is missed
in daily use, not by how hard it is.

## v2

### Skin switching as a feature, not a side effect

Right-click currently cycles to the next skin. That was the cheapest way to
prove multiple skins work, and it is the wrong interaction to keep: there is no
way to see what you are choosing between, no way to go back one, and no way to
reach a specific skin without clicking through the others.

Right-click should open an `NSMenu` listing the skins with the current one
ticked, plus Quit. The plumbing already exists — `rightMouseDown:` is bound and
`skins.list_skins()` already discovers folders on disk — so this is a menu, not
a redesign.

### DIY skins from a photo

Hand the agent an image and get a skin: a photo of a cat becomes a cat pet.
`list_skins()` already picks up any folder under `assets/skins/<id>/`, so
nothing in the app needs to change; the work is entirely in the art pipeline.

The pipeline is most of the way there. `generate_frames.py` is already
image-to-image only, which is exactly what turning one photo into 18 consistent
poses requires. What it does not yet do is derive the first still from an
arbitrary photo rather than from an existing skin's idle frame, and the
per-state prompts are written for creatures rather than for whatever arrives.

Open question worth settling before building it: a photo of a person is not a
photo of a cat. Turning someone's face into a chibi sprite is a different
transformation from restyling an animal, and the same prompt will not do both.

### Click-through on the transparent margin

The window is a 200px square and the character does not fill it, so clicks in
the corners hit the pet instead of whatever is behind it. The fix is a
`hitTest:` override returning nil for pixels whose alpha is below a threshold.
It is written and unit-tested against the frame data; what is missing is wiring
it into the AppKit view, which needs care because `hitTest:` runs on every
mouse move and must not decode a PNG each time.

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
