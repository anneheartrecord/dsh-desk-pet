# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

A desktop companion that floats above every window and changes expression with
your local DSH. Whale by default, four skins.

Not an in-page widget — a borderless, transparent system window. The pet in the
DSH page is a mirror of it.

[中文](README.md)

## Install

With DSH already set up, one command:

```bash
dsh plugin --profile web add github:anneheartrecord/dsh-desk-pet#main
```

On macOS it runs on the system `/usr/bin/python3`. No dependencies to install.

## Start

```bash
dsh web
```

The pet floats on your desktop. A synced mirror sits in the bottom-right of the
DSH page.

Pet only, no DSH: clone the repo and run `./bin/dsh-desk-pet`.

## Known limits

**Fullscreen apps cover it.** A macOS fullscreen app owns its own Space, and Tk
offers only a boolean always-on-top — not the `screen-saver` window level an
Electron pet can reach — so it cannot cross into that Space. The pet is hidden
while you are in a fullscreen video or editor, and returns when you leave. That
is Tk's ceiling, not a bug.

**Can't see the pet?** A borderless transparent window is the most fragile
rendering path there is. `--opaque` swaps it for a titled window on a solid
background; if that one shows up, the problem is transparency compositing
rather than the pet failing to start:

```bash
./bin/dsh-desk-pet --opaque
```

## Use

- **Drag**: grab it anywhere.
- **Click**: it hops. If it was dozing, it wakes up.
- **Switch skin**: right-click (or Control-click) for the menu, or press `1`–`4`.
  Switching skin never changes state.
- **Close**: `Esc` or `q`, or pick Quit from the right-click menu.

## States

Driven by your local DSH. Nothing to configure.

| State | When |
| --- | --- |
| idle | Nothing to do — breathes, blinks now and then |
| working | DSH is running |
| waiting | Blocked on a confirmation, approval, or your input |
| error | The run failed |
| happy | A run just finished; decays back to idle after a few seconds |
| sleeping | Dozes only when the agent is idle **and** your pointer has stopped moving; any activity or a poke wakes it |

## Skins

| Dot | id |
| --- | --- |
| Blue | `whale` (default) |
| Orange | `threadcore` |
| Brown | `nautilus` |
| Purple | `jellyfish` |

## Stop and uninstall

- Just the pet: press `Esc` on the window.
- Pet and DSH together: stop `dsh web`; the plugin's pet goes with it.
- Remove the plugin:

```bash
dsh plugin --profile web remove dsh-desk-pet
```

Then restart `dsh web`.

## Development

```bash
/usr/bin/python3 -m unittest discover -s tests -v   # full suite, no window needed
DSH_PET_ART_CHECK=1 /usr/bin/python3 -m unittest discover -s tests   # include the art gate (~10s more)
./bin/dsh-desk-pet --probe                          # diagnostics without mapping a window
./bin/dsh-desk-pet --inventory                      # frames per skin per state
./bin/dsh-desk-pet --small --reset                  # half size, and forget the saved position
```

### The art pipeline

Four scripts, in order:

```bash
./scripts/generate_frames.py       # fill in missing poses (needs ARTGEN__IMAGE_* in the env)
./scripts/build_frames.py          # key, align, scale; writes both frame sets
./scripts/check_frames.py          # per-pixel inspection
./scripts/contact_sheet.py         # one reviewable image, no window required
```

New art goes on a **magenta `#FF00FF` background**, and props (ZZZ, sparkles)
must not use magenta or the background colour. The plate has to be a colour the
artwork never contains: the first batch was generated on pastel plates — mint
green behind the jellyfish — close enough to the characters that no key
threshold could separate them, which is how that jellyfish shipped with its
eyes cut out. Magenta sits far from all four palettes, so the key tolerance can
be 0.24 and still take nothing off the character.

**generate_frames** never redraws the character from scratch: every request is
an image-to-image edit of an existing still. Text-to-image cannot hold identity
across calls — ask twice and you get two different whales, in two palettes, at
two scales, and the pet visibly mutates when its state changes. Frame 00 of a
state edits from the skin's idle rest pose; frame 01 edits from **frame 00 of
its own state**, because a two-frame loop needs the same pose an instant later,
not two different poses.

**build_frames** turns one still into two outputs: a transparent GIF under
`assets/skins/` for the desktop window (macOS ships Tk 8.5, whose `PhotoImage`
reads GIF and not PNG), and an RGBA PNG under `assets/web/` for the in-page
mirror. It uses ffmpeg's `colorkey`, not `chromakey`: the latter matches on
chroma alone and ignores luma, so against a pastel plate it deletes the
character's black eyes. After keying it seals interior holes — background is by
definition the transparency connected to the frame border, so anything cut out
*inside* the silhouette is damage and gets filled back in. The crop is computed
per skin in **relative** coordinates (sources arrive at 360, 1024 and 1254px)
and anchored on the body's baseline, so neither changing state nor changing
skin makes the pet jump or resize.

**check_frames** is the only test that looks at pixels. Everything else can
only compare filenames — which is how the jellyfish once passed the entire
suite with holes punched through its face.

Two or more frames in a state loop automatically. The second `idle` frame is
treated as the closed-eye pose and gets a long-open/short-shut double blink.

### Custom skins

A skin is just a folder of frames. Anything at
`assets/skins/<id>/<state>/*.gif` shows up in the right-click menu on its own,
with no code change.
