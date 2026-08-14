# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

[中文](README.md)

Always-on-top desktop pet for DeepSeek Harness. Default whale, four skins, four states. Not an in-page widget.

## Install

You already have DSH:

```bash
dsh plugin --profile web add github:anneheartrecord/dsh-desk-pet#main
```

Needs macOS `/usr/bin/python3` (with Tk).

## Start

```bash
dsh web
```

The pet appears when DSH boots. Drag it over the browser tab.

Pet only, no DSH:

```bash
./bin/dsh-desk-pet
```

## Use

- Drag anywhere on the window.
- Switch skin with the four dots (does not change state).
- States: idle / working / waiting / error. Follows local DSH by itself.

## Stop

- This pet: `Esc`.
- DSH and pet together: stop `dsh web`.
- Uninstall:

```bash
dsh plugin --profile web remove dsh-desk-pet
```

Then start `dsh web` again.

## Tests

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```
