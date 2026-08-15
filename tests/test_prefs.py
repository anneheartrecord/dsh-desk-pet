"""Saved position / size / skin. A bad prefs file must never stop the pet starting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dsh_desk_pet import prefs as prefs_store
from dsh_desk_pet.prefs import MAX_SCALE, MIN_SCALE, Prefs


class RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_saves_and_reloads(self) -> None:
        self.assertTrue(prefs_store.save(Prefs(skin_id="jellyfish", x=400, y=250, scale=0.5), self.home))
        loaded = prefs_store.load(self.home)
        self.assertEqual(loaded.skin_id, "jellyfish")
        self.assertEqual((loaded.x, loaded.y), (400, 250))
        self.assertEqual(loaded.scale, 0.5)

    def test_missing_file_gives_defaults(self) -> None:
        loaded = prefs_store.load(self.home / "nope")
        self.assertEqual(loaded.skin_id, "whale")
        self.assertIsNone(loaded.x)

    def test_corrupt_file_gives_defaults(self) -> None:
        path = prefs_store.prefs_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("}{", encoding="utf-8")
        self.assertEqual(prefs_store.load(self.home).skin_id, "whale")

    def test_unknown_keys_are_ignored(self) -> None:
        """A file written by a newer version must not crash an older pet."""

        path = prefs_store.prefs_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"skin_id":"nautilus","future_field":true}', encoding="utf-8")
        self.assertEqual(prefs_store.load(self.home).skin_id, "nautilus")

    def test_save_leaves_no_temp_files(self) -> None:
        for _ in range(4):
            prefs_store.save(Prefs(x=1, y=2), self.home)
        leftovers = [p.name for p in prefs_store.prefs_path(self.home).parent.iterdir()
                     if p.name.startswith(".prefs-")]
        self.assertEqual(leftovers, [])

    def test_save_to_unwritable_home_reports_failure(self) -> None:
        self.assertFalse(prefs_store.save(Prefs(), Path("/definitely/not/writable")))


class ClampTests(unittest.TestCase):
    def test_unknown_skin_falls_back_to_default(self) -> None:
        self.assertEqual(Prefs(skin_id="dragon").clamped().skin_id, "whale")

    def test_scale_is_clamped_both_ways(self) -> None:
        self.assertEqual(Prefs(scale=99).clamped().scale, MAX_SCALE)
        self.assertEqual(Prefs(scale=0.01).clamped().scale, MIN_SCALE)

    def test_garbage_scale_becomes_one(self) -> None:
        self.assertEqual(Prefs(scale="huge").clamped().scale, 1.0)  # type: ignore[arg-type]

    def test_negative_coordinates_are_kept(self) -> None:
        """A display to the left of the primary has them; they are not errors."""

        clamped = Prefs(x=-1200, y=-40).clamped()
        self.assertEqual((clamped.x, clamped.y), (-1200, -40))

    def test_absurd_position_is_discarded(self) -> None:
        clamped = Prefs(x=-999_999, y=999_999).clamped()
        self.assertIsNone(clamped.x)
        self.assertIsNone(clamped.y)

    def test_non_integer_position_is_discarded(self) -> None:
        clamped = Prefs(x="left", y=None).clamped()  # type: ignore[arg-type]
        self.assertIsNone(clamped.x)


if __name__ == "__main__":
    unittest.main()
