# DSH Desk Pet

<p align="center">
  <img src="docs/media/idle.gif" width="180" alt="The DeepSeek whale, breathing and blinking">
</p>

<p align="center">
  <b>A desk pet that shows you what your agent is doing.</b><br>
  It floats above every window — including fullscreen — and changes expression
  as DSH works, waits, finishes or fails.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-system%20only-3776AB.svg" alt="System Python">
  <img src="https://img.shields.io/badge/dependencies-none-2ea44f.svg" alt="No dependencies">
  <a href="https://github.com/topics/dsh-plugin"><img src="https://img.shields.io/badge/topic-dsh--plugin-111111.svg" alt="dsh-plugin"></a>
</p>

<p align="center">
  <img src="docs/media/states.png" width="720" alt="idle, working, waiting, error, happy, sleeping">
</p>
<p align="center">
  <sub>idle · working · waiting · error · happy · sleeping</sub>
</p>

<p align="center"><a href="README.zh-CN.md">中文</a></p>

---

## Install

With DSH already set up, one command:

```bash
dsh plugin --profile web add github:anneheartrecord/dsh-desk-pet#main
dsh web
```

The pet appears on your desktop, and a synced mirror sits in the bottom-right
of the DSH page.

Pet only, no DSH: clone the repo and run `./bin/dsh-desk-pet`.

**No dependencies.** It runs on the system `/usr/bin/python3` and talks to
AppKit through `ctypes`. Nothing to install, nothing to build.

## Use

| | |
|---|---|
| **Drag** | Grab it anywhere. Where you leave it is where it starts next time. |
| **Click** | Opens the session list — which DSH sessions exist, which is live, what it is doing. Click again to close. |
| **Right-click** | Cycles skins. |
| **Stop** | `./bin/dsh-desk-pet --stop`, or stop `dsh web`. |

It starts in the background and detaches from your terminal, so you can close
the window you launched it from.

## States

Driven by your local DSH. Nothing to configure.

| State | When |
| --- | --- |
| **idle** | Nothing to do — breathes, blinks now and then |
| **working** | DSH is running |
| **waiting** | Blocked on a confirmation, approval, or your input |
| **error** | The run failed |
| **happy** | A run just finished; settles back to idle after a few seconds |
| **sleeping** | Dozes when the agent is idle **and** your pointer has stopped moving. Any activity, or a poke, wakes it. |

That last one takes two clocks on purpose: an agent with nothing to do is not
the same thing as a desk with nobody at it.

## Skins

<p align="center">
  <img src="docs/media/skins.png" width="600" alt="Five skins">
</p>
<p align="center">
  <sub>DeepSeek Whale (default) · Blue Whale · Threadcore · Nautilus · Jellyfish</sub>
</p>

Right-click to cycle, or `--skin <id>`. Every skin has all six states at three
frames each.

## Options

```bash
./bin/dsh-desk-pet --scale 0.5      # smaller (default 0.7)
./bin/dsh-desk-pet --skin jellyfish # start on a specific skin
./bin/dsh-desk-pet --reset          # forget saved position, size and skin
./bin/dsh-desk-pet --stop           # stop the running pet
./bin/dsh-desk-pet --foreground     # stay attached, log to this terminal
./bin/dsh-desk-pet --probe          # diagnostics, no window
./bin/dsh-desk-pet --inventory      # frames per skin per state
```

## How it works

The pet watches `~/.dsh` — running processes, session activity, and an optional
hint file — and maps what it finds onto the six states. To drive it by hand:

```bash
echo '{"kind":"working"}' > ~/.dsh/pet-activity.json
rm ~/.dsh/pet-activity.json          # back to automatic
```

The desktop pet is the only thing that watches DSH. It publishes what it sees
to `~/.dsh-desk-pet/state.json`, and the in-page mirror reads that — one
implementation of "what is the agent doing", rather than two that can disagree.

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
/usr/bin/python3 -m unittest discover -s tests -v          # 145 tests, no display needed
DSH_PET_ART_CHECK=1 /usr/bin/python3 -m unittest discover -s tests   # + the pixel gate
node tests/plugin_smoke.mjs                                 # the plugin's HTTP routes
```

### The art pipeline

```bash
./scripts/generate_frames.py    # fill in missing poses
./scripts/build_frames.py       # key, align, scale; writes both frame sets
./scripts/check_frames.py       # per-pixel inspection
./scripts/contact_sheet.py      # one reviewable image, no window required
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

A skin is a folder of frames. Anything at `assets/skins/<id>/<state>/*.png`
appears in the cycle on its own, with no code change.

## Known limits

- The window is a rectangle, so clicks landing on the transparent margin around
  the pet do not reach what is behind it. Per-pixel click-through is written but
  not yet wired up.
- No menu yet — right-click cycles skins rather than opening one.

## License

MIT.
