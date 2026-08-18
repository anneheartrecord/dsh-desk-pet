"""Skins that live outside the package.

The installed copy sits in node_modules and is replaced wholesale on upgrade,
so anything written there would not survive one. A user's own skin lives in
their home directory instead, and discovery searches both roots.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dsh_desk_pet import packs, skins

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "web" / "deepseek"


class UserSkinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / ".dsh-desk-pet" / "skins"
        self.root.mkdir(parents=True)
        patcher = mock.patch.object(skins, "user_frame_root", lambda home=None: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        packs.reset_cache()
        self.addCleanup(packs.reset_cache)

    def _install(self, skin_id="mycat", states=None):
        target = self.root / skin_id
        for state in (states or [d.name for d in SOURCE.iterdir() if d.is_dir()]):
            src = SOURCE / state
            if not src.is_dir():
                continue
            shutil.copytree(src, target / state)
        return target

    def test_a_skin_in_the_user_root_is_discovered(self) -> None:
        self._install()
        packs.reset_cache()
        self.assertIn("mycat", [s.id for s in skins.list_skins()])

    def test_its_frames_resolve_and_the_loop_is_not_empty(self) -> None:
        """The defect this unit fixes.

        The empty-loop recheck tested the GIF tree, which a user skin never
        has, so it kept serving a cached empty loop and froze the sprite on its
        last frame.
        """

        self._install()
        packs.reset_cache()
        loop = packs.loop_for("mycat", "idle", web=True)
        self.assertTrue(loop.frames, "a user skin must not serve an empty loop")

    def test_a_skin_appearing_after_a_cached_miss_still_resolves(self) -> None:
        """The whole point of installing while the pet is running."""

        packs.reset_cache()
        self.assertFalse(packs.loop_for("mycat", "idle", web=True).frames)
        self._install()
        self.assertTrue(packs.loop_for("mycat", "idle", web=True).frames,
                        "a skin installed mid-session must become playable")

    def test_a_user_skin_cannot_shadow_a_builtin(self) -> None:
        self._install(skin_id="deepseek")
        packs.reset_cache()
        ids = [s.id for s in skins.list_skins()]
        self.assertEqual(ids.count("deepseek"), 1)
        self.assertTrue(skins.get_skin("deepseek").builtin)
        self.assertTrue(str(packs.skin_dir("deepseek", web=True)).startswith(str(ROOT)),
                        "the shipped tree must win")

    def test_a_folder_with_no_frames_is_ignored(self) -> None:
        (self.root / "empty").mkdir()
        packs.reset_cache()
        self.assertNotIn("empty", [s.id for s in skins.list_skins()])

    def test_per_skin_manifest_supplies_the_subject_box(self) -> None:
        target = self._install()
        (target / "manifest.json").write_text(
            json.dumps({"frame_size": 200, "subject_box": [10, 20, 180, 190], "format": 1}),
            encoding="utf-8")
        packs.reset_cache()
        self.assertEqual(packs.subject_box("mycat"), (10, 20, 180, 190))

    def test_a_manifest_corrupted_after_install_degrades_instead_of_raising(self) -> None:
        """It is read on the render path, inside an Objective-C callback."""

        target = self._install()
        (target / "manifest.json").write_text("{ not json", encoding="utf-8")
        packs.reset_cache()
        self.assertIsNone(packs.subject_box("mycat"))
        self.assertTrue(packs.loop_for("mycat", "idle", web=True).frames)

    def test_a_manifest_with_a_broken_timeline_falls_back(self) -> None:
        target = self._install()
        (target / "manifest.json").write_text(
            json.dumps({"timelines": {"idle": "not-a-list"}}), encoding="utf-8")
        packs.reset_cache()
        loop = packs.loop_for("mycat", "idle", web=True)
        self.assertTrue(loop.frames)
        self.assertGreater(loop.timeline.total_ms, 0)


class ShippedArtIsolationTests(unittest.TestCase):
    """A user's skin must never be measured against gates written for ours.

    The art assertions iterate the builtin list rather than the discovered
    catalog. Otherwise installing a skin fails the suite for art we did not
    make, and the tempting repair is to loosen a gate that protects the shipped
    set.
    """

    def test_the_builtin_list_is_what_the_art_gates_iterate(self) -> None:
        self.assertEqual(
            [s.id for s in skins.BUILTIN_SKINS],
            ["deepseek", "bluewhale", "threadcore", "nautilus", "jellyfish"],
        )
        for skin in skins.BUILTIN_SKINS:
            self.assertTrue(skin.builtin)


if __name__ == "__main__":
    unittest.main()
