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
import tempfile
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
    "proportions as the reference image. Keep the identical flat magenta background colour "
    "filling the entire frame edge to edge, with no gradient, no shadow and no border. Keep the "
    "same framing, the same body scale and the same position in frame. Any added props, glyphs "
    "or sparkles must be drawn in colours taken from the character's own palette — never magenta "
    "and never the background colour, or they will be cut away with the background. Change "
    "nothing except the pose and facial expression described next."
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
        # Not a blink. An earlier pass made 01 a closed-eye frame, which is what
        # idle/01 already is — so half of `working` was pixel-identical to idle,
        # and the state's only signifier vanished every other frame.
        "01": (
            "The same concentrating pose one instant later, mid-action: the hand and its tool have "
            "moved to a clearly different position, as though partway through a stroke. Eyes stay "
            "open and focused on the work, brow still furrowed. Body, scale and framing unchanged."
        ),
        "02": (
            "The same concentrating pose again, still holding the tool in view, but with the eyes "
            "briefly closed in a quick blink. The tool must remain visible and in the same place "
            "as the reference."
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
        "02": (
            "The same waiting pose again, mid-glance: eyes rolled to look off to one side as if "
            "checking whether anyone is coming, head still tilted, question mark still beside the "
            "head. Same flat mouth, same body."
        ),
    },
    "error": {
        "01": (
            "The same upset pose one instant later, crying harder: eyes squeezed shut into tight "
            "downward arcs, two large tears flying outward, mouth open in a small wail. Keep the "
            "body at exactly the same size and the same degree of disarray as the reference."
        ),
        "02": (
            "The same upset pose between sobs: eyes open but watery and downturned, mouth a small "
            "wobbling frown, a single tear still on the cheek. Body the same size and the same "
            "degree of disarray as the reference."
        ),
    },
    "happy": {
        "00": (
            "Delighted celebration: both arms thrown up in the air, huge open smile, eyes curved "
            "into happy arcs, cheeks blushing, a few small sparkles around the head."
        ),
        "01": (
            "The same delighted celebration one instant later: eyes shut in a joyful squint, mouth "
            "wider, sparkles drifted further out. Keep the body at exactly the same size — a change "
            "in scale between frames of one loop reads as the pet pulsing."
        ),
        "02": (
            "The same celebration again, arms at the top of their swing and eyes wide open and "
            "shining, mouth still in a big open smile, sparkles at their brightest. Body at "
            "exactly the same size as the reference."
        ),
    },
    "sleeping": {
        # The silhouette has to change, not just the props. Closed eyes plus a
        # ZZZ over an otherwise upright body is indistinguishable from an idle
        # blink at display size, and leaves a small floating glyph carrying the
        # whole state.
        "00": (
            "Fast asleep and visibly slumped: the whole body settled downward and squashed wider "
            "and flatter than the reference, head drooping forward and tipped to one side, "
            "shoulders collapsed. Eyes closed in gentle downward curves, a soft blush, and a small "
            "trail of ZZZ letters floating up from the head."
        ),
        "01": (
            "The same slumped sleeping pose on a deeper breath: body settled a little lower and "
            "wider still, head drooped slightly further, eyes still closed, the ZZZ letters "
            "drifted higher and fainter."
        ),
        "02": (
            "The same slumped sleeping pose at the top of a breath in: body drawn a little taller "
            "and narrower than the reference, head lifted very slightly, eyes still closed, a fresh "
            "small ZZZ just leaving the head."
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


# Re-plating prompt. The plate the art was generated on is a pastel that sits
# close to the characters themselves — the jellyfish's mint background is within
# keying distance of its own pale highlights — which is why no threshold ever
# separated them cleanly. Magenta appears nowhere in any of these palettes, so
# the key becomes unambiguous instead of merely well-tuned.
REPLATE_PROMPT = (
    "Keep the character exactly as it is: same art style, colour palette, line weight, shading, "
    "proportions, pose, expression, framing and size. Change ONLY the background: replace it with "
    "pure saturated magenta, hex #FF00FF, completely flat and uniform, filling the entire frame "
    "edge to edge behind the character. No gradient, no shadow, no glow, no vignette. The "
    "character itself must not take on any magenta."
)


def _is_magenta(path: Path) -> bool:
    """Does this still already sit on the keyable plate?"""

    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "crop=12:12:0:0,scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or len(proc.stdout) < 3:
        return False
    r, g, b = proc.stdout[0], proc.stdout[1], proc.stdout[2]
    return r > 180 and g < 90 and b > 180


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


def generate(
    skin: str, state: str, index: str, delta: str, *, force: bool, replate: bool = False
) -> tuple[str, str]:
    dest = SOURCE_ROOT / skin / state / f"{index}.png"
    if replate:
        # Edit the frame in place: the pose is already right, only its plate is
        # being swapped, so the frame is its own reference.
        reference = dest
        if not reference.is_file():
            return f"{skin}/{state}/{index}", "skip (nothing to re-plate)"
        if _is_magenta(dest):
            # Idempotent, so a run can be repeated to pick up failures without
            # sending every already-converted frame through the model again and
            # letting it drift.
            return f"{skin}/{state}/{index}", "skip (already magenta)"
        prompt = REPLATE_PROMPT
    else:
        if dest.is_file() and not force:
            return f"{skin}/{state}/{index}", "skip (exists)"
        reference = reference_for(skin, state, index)
        if not reference.is_file():
            return f"{skin}/{state}/{index}", f"FAIL no reference at {reference}"
        subject = SKIN_SUBJECT.get(skin, "character")
        prompt = f"{IDENTITY} The character is a cute chibi {subject}. {delta}"

    url, key = _endpoint()
    # The Authorization header goes through a 0600 config file, never argv:
    # anything on `curl -H "Bearer ..."` is readable by every process on the
    # machine via `ps`, and this key is the user's real one.
    header_fd, header_file = tempfile.mkstemp(prefix=".artgen-", suffix=".conf")
    with os.fdopen(header_fd, "w", encoding="utf-8") as handle:
        handle.write(f'header = "Authorization: Bearer {key}"\n')

    # curl rather than urllib: multipart with a file part is a lot of boilerplate
    # in the stdlib, and curl is already required by the rest of this repo's tooling.
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "--noproxy", "*", "--max-time", str(TIMEOUT_S),
                "-K", header_file,
                "-X", "POST", url,
                "-F", f"model={MODEL}",
                "-F", f"image=@{reference}",
                "-F", f"size={SIZE}",
                "-F", "n=1",
                "-F", f"prompt={prompt}",
            ],
            capture_output=True,
        )
    finally:
        Path(header_file).unlink(missing_ok=True)
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
    parser.add_argument(
        "--replate",
        action="store_true",
        help="keep every existing pose, swap its background for a keyable magenta",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    skins = args.skin or sorted(p.name for p in SOURCE_ROOT.iterdir() if p.is_dir())

    if args.replate:
        # Every still on disk, not just the ones this script knows how to pose.
        jobs = [
            (skin, path.parent.name, path.stem, "")
            for skin in skins
            for path in sorted((SOURCE_ROOT / skin).glob("*/*.png"))
        ]
    else:
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
    # previous build's 00. Re-plating has no such dependency — each frame is its
    # own reference — so it goes in one wave.
    if args.replate:
        waves = [jobs]
    else:
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
            futures = {
                pool.submit(generate, *job, force=args.force, replate=args.replate): job
                for job in wave
            }
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
