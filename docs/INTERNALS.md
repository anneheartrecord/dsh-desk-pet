# Internals

<p align="center"><b>English</b> · <a href="INTERNALS.zh-CN.md">简体中文</a></p>

> How to use it is in the [README](../README_EN.md). This page is how it works inside,
> and the places where the first choice turned out to be the wrong one.

## How it works

The pet watches `~/.dsh` — running processes, session activity, and an optional
hint file — and maps what it finds onto the six states. To drive it by hand:

```bash
echo '{"kind":"working"}' > ~/.dsh/pet-activity.json
rm ~/.dsh/pet-activity.json          # back to automatic
```

The pet publishes what it sees to `~/.dsh-desk-pet/state.json`, which is how a
second launch knows one is already running and how `--stop` finds it.

There was briefly a second pet mirrored into the DSH page. It is gone: two pets
on one screen read as a bug, and the mirror was where the failures lived. The
window that floats over everything is the thing worth having.

### Why AppKit and not Tk

macOS ships Tcl/Tk 8.5.9, released in 2010, and on macOS 26 its drawing path no
longer reaches the screen: the window maps, the canvas reports itself mapped,
viewable, correctly sized and holding an image at the right coordinates — and
what appears is an empty grey rectangle.

So the window is built directly on AppKit through `ctypes`. That is more
machinery, and it buys three things Tk could not offer at all: real alpha
instead of a 1-bit GIF matte, a window level that clears fullscreen Spaces, and
a session panel that travels with the pet as a child window.

## Development

```bash
/usr/bin/python3 -m unittest discover -t . -s tests -v     # 267 tests, no display needed
DSH_PET_ART_CHECK=1 /usr/bin/python3 -m unittest discover -t . -s tests   # + the pixel gate
node tests/plugin_smoke.mjs                                 # the plugin's HTTP routes
```

### The art pipeline

```bash
./scripts/generate_frames.py    # fill in missing poses
./scripts/build_frames.py       # key, align, scale; writes both frame sets
./scripts/check_frames.py       # per-pixel inspection
./scripts/contact_sheet.py      # one reviewable image, no window required
./scripts/media_sheets.py       # the preview strips and loops the READMEs show
```

New art goes on a **magenta `#FF00FF` background**, and props must not use
magenta. The plate has to be a colour the artwork never contains: the first
batch was generated on pastel plates — mint green behind the jellyfish — close
enough to the characters that no key threshold could separate them, which is how
that jellyfish once shipped with its eyes cut out.

**generate_frames** never redraws a character from scratch; every request is an
image-to-image edit of an existing still, because text-to-image cannot hold
identity across calls. Frame `00` of a state edits from the skin's idle pose;
frame `01` edits from **frame 00 of its own state**, because a loop needs the
same pose an instant later, not two different poses.

**check_frames** is the only test that looks at pixels. Everything else can
only compare filenames — which is how a skin once passed the entire suite with
holes punched through its face.

### Custom skins

A skin is a folder of frames. Anything at `assets/web/<id>/<state>/*.png`
appears in the cycle on its own, with no code change.
