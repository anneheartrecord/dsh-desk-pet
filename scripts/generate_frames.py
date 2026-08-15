#!/usr/bin/env /usr/bin/python3
"""Generate the missing pose frames for each skin, without redrawing the character.

Every request is an *edit* of that skin's `idle/00.png`, never a fresh
generation. Text-to-image cannot hold a character's identity across calls — ask
twice and you get two different whales, in two different palettes, at two
different scales, and the pet visibly mutates when its state changes. Editing
from one locked reference keeps silhouette, palette, line weight, framing and
the flat background plate identical, so `build_frames.py` can key every frame
with the same colour and crop them all to the same box.

The prompts deliberately ask for a *small* delta on the second frame of a state.
Two frames only read as a loop if they are the same pose an instant apart; two
different poses read as a glitch.

Needs `ARTGEN__IMAGE_BASE_URL` and `ARTGEN__IMAGE_API_KEY` in the environment
(they come from ~/.config/secrets/api-keys.env via ~/.zshenv).

    ./scripts/generate_frames.py                    # only what is missing
    ./scripts/generate_frames.py --skin whale       # one skin
    ./scripts/generate_frames.py --force            # redo everything
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "assets" / "source"

MODEL = "gpt-image-2"
SIZE = "1024x1024"
TIMEOUT_S = 300

# What each skin *is*, so the prompt can name the body parts it should move.
SKIN_SUBJECT = {
    "whale": "baby whale",
    "threadcore": "ball of yarn character with trailing threads",
    "nautilus": "nautilus shell creature",
    "jellyfish": "jellyfish with tentacles",
}

# Held constant across every request. This is what stops the pet mutating.
IDENTITY = (
    "Keep the exact same character, art style, colour palette, line weight, shading and "
    "proportions as the reference image. Keep the identical flat background colour filling "
    "the entire frame edge to edge, with no gradient, no shadow and no border. Keep the same "
    "framing, the same body scale and the same position in frame. Change nothing except the "
    "pose and facial expression described next."
)

# state -> frame index -> the delta to apply.
POSES: dict[str, dict[str, str]] = {
    "idle": {
        # The in-between of the blink. The Codex atlas spends its two shortest
        # holds (110ms) on exactly this frame, and it is the whole reason its
        # idle reads as an eyelid moving rather than eyes cutting to black.
        "02": (
            "Identical to the reference in every way except the eyes, which are half closed: "
            "upper eyelids drawn down to cover the top half of each eye, pupils still visible "
            "underneath. Mid-blink, caught between open and shut. Do not change the mouth, the "
            "head angle, the body or anything else."
        ),
    },
    "working": {
        "01": (
            "Same concentrating working pose as the reference's working frame, one instant later: "
            "eyes briefly closed in a quick blink, head tipped very slightly forward. "
            "Everything else identical."
        ),
    },
    # `waiting` means "blocked on you", and it has to be legible as *that*, not
    # as cheerfulness. An earlier pass drew it as a happy wave, which made the
    # one state that needs to summon the user look identical to the celebration.
    "waiting": {
        "00": (
            "Waiting for an answer and mildly impatient: head tilted to one side, one eyebrow "
            "raised higher than the other, eyes looking straight at the viewer, mouth a small flat "
            "line, one hand raised beside the head holding up a single question mark."
        ),
        "01": (
            "The same waiting pose an instant later: head tilted a little further, eyes narrowed "
            "slightly, the question mark beside the head tipped over at an angle. Still the same "
            "flat mouth. Not smiling, not celebrating."
        ),
    },
    "error": {
        "01": (
            "The same upset pose one instant later, crying harder: eyes squeezed shut into tight "
            "downward arcs, two large tears flying outward, mouth open in a small wail. Keep the "
            "body at exactly the same size and the same degree of disarray as the reference."
        ),
    },
    "happy": {
        "00": (
            "Delighted celebration: both arms thrown up in the air, huge open smile, eyes curved "
            "into happy arcs, cheeks blushing, a few small sparkles around the head."
        ),
        "01": (
            "The same delighted celebration one instant later: eyes shut in a joyful squint, mouth "
            "wider, sparkles drifted further out. Keep the body at exactly the same size — this is "
            "the second frame of a two-frame loop, so a change in scale reads as the pet pulsing."
        ),
    },
    "sleeping": {
        "00": (
            "Fast asleep: eyes closed in gentle downward curves, a soft blush, a small trail of "
            "ZZZ letters floating up from the head, body relaxed and slumped down a little."
        ),
        "01": (
            "The same sleeping pose on a deeper breath: body settled lower and slightly wider, eyes "
            "still closed, the ZZZ letters drifted a little higher and fainter."
        ),
    },
}


def _endpoint() -> tuple[str, str]:
    base = os.environ.get("ARTGEN__IMAGE_BASE_URL", "").rstrip("/")
    key = os.environ.get("ARTGEN__IMAGE_API_KEY") or os.environ.get("ARTGEN_IMAGE_API_KEY", "")
    if not base or not key:
        raise SystemExit(
            "ARTGEN__IMAGE_BASE_URL / ARTGEN__IMAGE_API_KEY are not set.\n"
            "They live in ~/.config/secrets/api-keys.env and are exported by ~/.zshenv."
        )
    return f"{base}/images/edits", key


def reference_for(skin: str, state: str, index: str) -> Path:
    """Which still to edit from.

    Frame 00 of a state is a new pose, so it edits from the skin's idle rest
    pose. Frame 01 is the *same* pose an instant later, so it edits from frame
    00 of its own state — editing it from idle instead produced a second frame
    that shared nothing with the first, and the loop read as the character
    exploding and re-forming once a second.
    """

    if index != "00":
        sibling = SOURCE_ROOT / skin / state / "00.png"
        if sibling.is_file():
            return sibling
    return SOURCE_ROOT / skin / "idle" / "00.png"


def generate(skin: str, state: str, index: str, delta: str, *, force: bool) -> tuple[str, str]:
    dest = SOURCE_ROOT / skin / state / f"{index}.png"
    if dest.is_file() and not force:
        return f"{skin}/{state}/{index}", "skip (exists)"

    reference = reference_for(skin, state, index)
    if not reference.is_file():
        return f"{skin}/{state}/{index}", f"FAIL no reference at {reference}"

    url, key = _endpoint()
    subject = SKIN_SUBJECT.get(skin, "character")
    prompt = f"{IDENTITY} The character is a cute chibi {subject}. {delta}"

    # curl rather than urllib: multipart with a file part is a lot of boilerplate
    # in the stdlib, and curl is already required by the rest of this repo's tooling.
    proc = subprocess.run(
        [
            "curl", "-s", "--noproxy", "*", "--max-time", str(TIMEOUT_S),
            "-X", "POST", url,
            "-H", f"Authorization: Bearer {key}",
            "-F", f"model={MODEL}",
            "-F", f"image=@{reference}",
            "-F", f"size={SIZE}",
            "-F", "n=1",
            "-F", f"prompt={prompt}",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        return f"{skin}/{state}/{index}", f"FAIL curl rc={proc.returncode}"

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return f"{skin}/{state}/{index}", f"FAIL bad json: {proc.stdout[:160]!r}"
    if "error" in payload:
        return f"{skin}/{state}/{index}", f"FAIL api: {json.dumps(payload['error'])[:200]}"

    try:
        item = payload["data"][0]
    except (KeyError, IndexError):
        return f"{skin}/{state}/{index}", f"FAIL no image in {json.dumps(payload)[:160]}"

    # The relay answers `/images/generations` with base64 but `/images/edits`
    # with a URL and an *empty* b64_json field, so presence is not enough —
    # this has to check for actual content or it silently writes 0-byte files.
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob = item.get("b64_json") or ""
    if blob:
        dest.write_bytes(base64.b64decode(blob))
    elif item.get("url"):
        fetch = subprocess.run(
            ["curl", "-s", "--noproxy", "*", "--max-time", str(TIMEOUT_S), "-o", str(dest), item["url"]],
            capture_output=True,
        )
        if fetch.returncode != 0:
            return f"{skin}/{state}/{index}", f"FAIL download rc={fetch.returncode}"
    else:
        return f"{skin}/{state}/{index}", f"FAIL empty payload {json.dumps(item)[:160]}"

    size = dest.stat().st_size
    if size < 10_000:
        dest.unlink(missing_ok=True)
        return f"{skin}/{state}/{index}", f"FAIL truncated ({size} bytes)"
    return f"{skin}/{state}/{index}", f"ok ({size // 1024} KB)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skin", action="append", help="limit to these skins")
    parser.add_argument("--state", action="append", help="limit to these states")
    parser.add_argument("--force", action="store_true", help="regenerate frames that already exist")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    skins = args.skin or sorted(p.name for p in SOURCE_ROOT.iterdir() if p.is_dir())
    states = args.state or list(POSES)

    jobs = [
        (skin, state, index, delta)
        for skin in skins
        for state in states
        for index, delta in POSES.get(state, {}).items()
    ]
    if not jobs:
        print("nothing to do")
        return 0

    # Two passes, because frame 01 of a state edits from frame 00 of that same
    # state. Run them together and 01 either races a missing file or edits the
    # previous build's 00.
    waves = [
        [job for job in jobs if job[2] == "00"],
        [job for job in jobs if job[2] != "00"],
    ]
    print(f"{len(jobs)} frames across {len(skins)} skins, {args.workers} at a time")

    failures = 0
    for wave in waves:
        if not wave:
            continue
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(generate, *job, force=args.force): job for job in wave}
            for future in as_completed(futures):
                name, status = future.result()
                if status.startswith("FAIL"):
                    failures += 1
                print(f"  {name:28s} {status}")

    print(f"done, {failures} failed")
    if failures:
        return 1
    print("next: ./scripts/build_frames.py && ./scripts/contact_sheet.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
