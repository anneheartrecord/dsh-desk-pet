"""Assert the shipped frames as pixels.

Every other test in this suite can only see filenames. That is exactly how the
jellyfish once shipped with its eyes keyed out and sixty holes through its body
while the whole suite stayed green: a ruined GIF is still a GIF of the right
name, in the right folder, differing from its neighbours.

This runs `scripts/check_frames.py`, which decodes each frame and flood-fills
from the border to tell background apart from damage. It takes a few seconds —
slower than the rest of the suite put together — so it is skipped unless
`DSH_PET_ART_CHECK=1`, and always run before publishing art.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_frames.py"

RUN = os.environ.get("DSH_PET_ART_CHECK") == "1"


@unittest.skipUnless(RUN, "set DSH_PET_ART_CHECK=1 to decode every frame (~10s)")
class ArtIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(
            [sys.executable, str(CHECKER), "--json"], capture_output=True, text=True, timeout=300
        )
        cls.report = json.loads(proc.stdout)

    def test_no_frame_has_art_keyed_out_of_it(self) -> None:
        self.assertEqual(self.report["failures"], [], "\n".join(self.report["failures"]))

    def test_every_frame_actually_contains_a_subject(self) -> None:
        for key, entry in self.report["frames"].items():
            self.assertGreater(entry["coverage"], 0.05, f"{key} is very nearly empty")
            self.assertLess(entry["coverage"], 0.90, f"{key} was never keyed")

    def test_skins_share_a_baseline(self) -> None:
        """Otherwise switching skin makes the pet hop up or down the screen."""

        self.assertLess(self.report.get("baseline_spread", 0), 14)


if __name__ == "__main__":
    unittest.main()
