"""Is a newer version published?

Deliberately small, and deliberately not clever. Three things shape it:

* **The answer is read when the menu opens, not when the item is clicked.** An
  `NSMenu` dismisses the moment an item is picked, so a result rendered in
  response to a click is shown to a menu nobody is looking at. Clicking would
  look like it did nothing.
* **"Could not reach the registry" is not "up to date."** Treating a failure as
  current would tell a user they are on the latest build forever, including
  when the thing they are missing is a fix.
* **The package name comes from the manifest, never a literal.** The npm
  package is `deepseek-desk-pet` while the repo, the launcher and the skill are
  all `dsh-desk-pet`; npm refused the matching name because an unrelated
  package was too similar. Hard-coding the wrong one would query somebody
  else's package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REGISTRY = "https://registry.npmjs.org"
TIMEOUT_S = 5.0
# Enough for a registry document; a hostile or broken response does not get to
# stream into memory.
MAX_BYTES = 512 * 1024
# How long a fetched answer is trusted before the next menu open refreshes it.
CACHE_MS = 6 * 60 * 60 * 1000

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")

MANIFEST = Path(__file__).resolve().parents[2] / "package.json"


def _manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def package_name() -> str:
    return str(_manifest().get("name") or "")


def installed_version() -> str:
    return str(_manifest().get("version") or "")


def parse(version: str) -> tuple[int, int, int] | None:
    """A release triple, or None for anything that is not one.

    A `#main` install carries whatever version the branch happens to hold, so
    an unparseable value reports neutrally rather than as permanently behind.
    """

    match = _SEMVER.match(str(version).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(published: str, installed: str) -> bool:
    """Compare release triples. 0.10.0 is above 0.9.0, which string order is not."""

    left, right = parse(published), parse(installed)
    if left is None or right is None:
        return False
    return left > right


def fetch_published(name: str, opener=None) -> str | None:
    """The registry's latest version, or None if it could not be read."""

    if not name:
        return None
    url = f"{REGISTRY}/{name}/latest"
    if not url.startswith("https://"):
        return None
    try:
        if opener is None:
            from urllib.request import urlopen

            opener = urlopen
        with opener(url, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read(MAX_BYTES).decode("utf-8", "replace"))
    except Exception:
        # Every failure is the same answer to the caller: we do not know.
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or parse(version) is None:
        return None
    return version


def label(installed: str, published: str | None, upgrade_hint: str = "") -> str:
    """What the menu item reads.

    `published is None` means the check failed or has not run, which is a
    different statement from being current.
    """

    if published is None:
        return "Check for Updates"
    if parse(installed) is None:
        # A branch build. Comparing it against a release is meaningless.
        return "Check for Updates"
    if is_newer(published, installed):
        hint = f" — {upgrade_hint}" if upgrade_hint else ""
        return f"Update available: {published}{hint}"
    return "Up to date"


def unreachable_label() -> str:
    return "Could not check for updates"
