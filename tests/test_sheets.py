"""The preview sheet, which is the only artefact a user can hand to anyone.

A skin made from someone's photo lives in their home directory and nowhere
else. This image is how it leaves that machine, so the parts worth testing are
the ones that decide whether it can be produced at all: that a user skin is
drawable, that the width follows the number of states rather than a constant,
and that a bad id fails with something a person can act on rather than a
traceback out of the PNG decoder.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dsh_desk_pet import imaging, packs, sheets, skins

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "web" / "deepseek"


def _size(path: Path) -> tuple[int, int]:
    width, height, _ = imaging.decode_png(path.read_bytes())
    return width, height


class SheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.root = self.dir / "skins"
        self.root.mkdir()
        patcher = mock.patch.object(skins, "user_frame_root", lambda home=None: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        packs.reset_cache()
        self.addCleanup(packs.reset_cache)

    def _install(self, skin_id: str, states=None) -> Path:
        target = self.root / skin_id
        for state in (states or [d.name for d in SOURCE.iterdir() if d.is_dir()]):
            src = SOURCE / state
            if src.is_dir():
                shutil.copytree(src, target / state)
        packs.reset_cache()
        return target

    def test_a_shipped_skin_draws_all_six_states(self) -> None:
        out = sheets.build_strip("deepseek", self.dir / "sheet.png")
        expected = sheets.PAD * 2 + sheets.CELL * 6 + sheets.GAP * 5
        self.assertEqual(_size(out), (expected, sheets.PAD * 2 + sheets.CELL))

    def test_a_skin_only_in_the_user_root_draws(self) -> None:
        """The whole reason this ships: the skin being shared is never in the
        package, it is in the home directory of whoever generated it."""

        self._install("fromphoto")
        out = sheets.build_strip("fromphoto", self.dir / "user.png")
        self.assertTrue(out.is_file())
        self.assertGreater(out.stat().st_size, 0)

    def test_width_follows_the_states_a_skin_actually_has(self) -> None:
        """A half-finished skin should still produce a picture.

        The generator can fail partway and leave four states installed; a sheet
        that assumed six would read past the end or pad with empty cells, and
        neither is something to hand to another person.
        """

        self._install("partial", states=["idle", "working", "happy"])
        out = sheets.build_strip("partial", self.dir / "partial.png")
        expected = sheets.PAD * 2 + sheets.CELL * 3 + sheets.GAP * 2
        self.assertEqual(_size(out)[0], expected)

    def test_an_unknown_skin_says_what_to_do(self) -> None:
        with self.assertRaises(sheets.SheetError) as caught:
            sheets.build_strip("no-such-skin", self.dir / "nope.png")
        self.assertIn("--inventory", str(caught.exception))

    def test_a_missing_parent_directory_is_created(self) -> None:
        """`--out` is typed by a person, often into a folder they have in mind
        rather than one that exists."""

        out = sheets.build_strip("deepseek", self.dir / "a" / "b" / "sheet.png")
        self.assertTrue(out.is_file())

    def test_the_plate_is_opaque_where_the_character_is_not(self) -> None:
        """Shared straight into a chat window or a PR, a sheet with holes in it
        renders on whatever background that surface uses."""

        out = sheets.build_strip("deepseek", self.dir / "opaque.png")
        width, height, pixels = imaging.decode_png(out.read_bytes())
        for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width // 2, 2)):
            self.assertEqual(pixels[(y * width + x) * 4 + 3], 255,
                             f"({x},{y}) is transparent")


if __name__ == "__main__":
    unittest.main()
