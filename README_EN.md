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
| sleeping | Dozes off after five idle minutes; any activity or a poke wakes it |

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
./bin/dsh-desk-pet --probe                          # diagnostics without mapping a window
./bin/dsh-desk-pet --inventory                      # frames per skin per state
```

### Adding art

Drop stills in `assets/source/<skin>/<state>/NN.png` on any flat background —
the key colour is sampled from each image's own corners. Then:

```bash
./scripts/build_frames.py          # key, align, scale; writes both frame sets
./scripts/contact_sheet.py         # one reviewable image, no window required
```

`build_frames.py` turns one still into two outputs: a transparent GIF under
`assets/skins/` for the desktop window (macOS ships Tk 8.5, whose `PhotoImage`
reads GIF and not PNG), and an RGBA PNG under `assets/web/` for the in-page
mirror. The crop box is computed once **per skin**, so changing state never
makes the pet jump or resize.

Two or more frames in a state loop automatically. The second `idle` frame is
treated as the closed-eye pose and gets a long-open/short-shut double blink.
