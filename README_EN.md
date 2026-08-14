# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

[中文](README.md)

Always-on-top desktop companion for DeepSeek Harness. Four silent display states (idle, working, waiting, error). Default skin is whale; four first-party skins ship. This is **not** an in-page widget — installing it into DSH launches a system window you can drag over the browser.

## Install into DSH

The repo is a Cordis bundle (`dsh.bundle` + `cordis.patch.yml`) and is tagged `dsh-plugin`.

```bash
dsh plugin --profile web add "github:anneheartrecord/dsh-desk-pet#main"
dsh --profile web web
```

Or run the pet alone:

```bash
./bin/dsh-desk-pet
```

Uses macOS `/usr/bin/python3` (Tk). Esc quits. The four dots switch skins without changing state.

## Tests

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```
