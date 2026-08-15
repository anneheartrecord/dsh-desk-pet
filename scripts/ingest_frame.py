#!/usr/bin/env python3
"""Copy a generated still into a skin/state pack and emit a Tk-friendly GIF."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ingest(src: Path, skin: str, state: str, stem: str) -> None:
    dest_dir = ROOT / "assets" / "skins" / skin / state
    dest_dir.mkdir(parents=True, exist_ok=True)
    png = dest_dir / f"{stem}.png"
    gif = dest_dir / f"{stem}.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale=360:360:flags=lanczos",
            str(png),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["sips", "-s", "format", "gif", str(png), "--out", str(gif)], check=True, capture_output=True)
    print(f"WROTE {png} {png.stat().st_size} {gif} {gif.stat().st_size}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("skin")
    p.add_argument("state")
    p.add_argument("stem")
    args = p.parse_args()
    ingest(Path(args.src), args.skin, args.state, args.stem)


if __name__ == "__main__":
    main()
