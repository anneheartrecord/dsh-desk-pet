"""Installing a generated skin. All-or-nothing, and never destructive."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dsh_desk_pet import imaging, skininstall, skins

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "web" / "deepseek"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / ".dsh-desk-pet" / "skins"
        self.root.mkdir(parents=True)
        patcher = mock.patch.object(skins, "user_frame_root", lambda home=None: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.src = self.home / "generated"
        shutil.copytree(SOURCE, self.src)

    def _break_frame(self, state="idle", name="00.png", fill=(255, 0, 255, 255)):
        """Rewrite one frame as a flat colour of our choosing."""

        size = imaging.FRAME_SIZE
        raw = bytearray(bytes(fill) * (size * size))
        imaging._write_png_rgba(self.src / state / name, size, size, bytes(raw))


class HappyPathTests(_Base):
    def test_installs_and_becomes_discoverable(self) -> None:
        path = skininstall.install(self.src, "mycat", home=self.home)
        self.assertTrue(path.is_dir())
        self.assertIn("mycat", [s.id for s in skins.list_skins()])

    def test_writes_a_manifest_carrying_a_subject_box_and_format(self) -> None:
        """Without a subject box the skin swallows clicks on its empty corners."""

        path = skininstall.install(self.src, "mycat", home=self.home)
        payload = json.loads((path / skininstall.MANIFEST).read_text())
        self.assertEqual(payload["format"], 1)
        box = payload["subject_box"]
        self.assertEqual(len(box), 4)
        self.assertLess(box[0], box[2])
        self.assertLess(box[1], box[3])

    def test_marker_carries_only_declared_fields(self) -> None:
        """A skin is a directory a user will zip and send; the marker travels."""

        path = skininstall.install(self.src, "mycat", home=self.home,
                                   generator="gemini-3.1-flash-image")
        marker = json.loads((path / skininstall.MARKER).read_text())
        self.assertEqual(set(marker), {"format", "installed_at", "frames", "generator"})

    def test_a_key_shaped_generator_label_is_truncated(self) -> None:
        path = skininstall.install(self.src, "mycat", home=self.home, generator="k" * 5000)
        marker = json.loads((path / skininstall.MARKER).read_text())
        self.assertLessEqual(len(marker["generator"]), skininstall.MAX_LABEL)


class RefusalTests(_Base):
    def test_a_missing_state_is_refused_and_nothing_is_written(self) -> None:
        shutil.rmtree(self.src / "waiting")
        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_fully_opaque_frame_is_refused(self) -> None:
        """The likeliest failure: the model ignored the plate instruction.

        It passes a coverage floor more easily than good art does, which is why
        a floor alone is not enough.
        """

        self._break_frame(fill=(255, 0, 255, 255))
        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertIn("never removed", str(caught.exception))

    def test_an_empty_frame_is_refused(self) -> None:
        self._break_frame(fill=(0, 0, 0, 0))
        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertIn("missing", str(caught.exception))

    def test_an_undecodable_frame_is_refused(self) -> None:
        (self.src / "idle" / "00.png").write_bytes(b"\xff\xd8\xff not a png")
        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, "mycat", home=self.home)

    def test_a_failure_leaves_no_staging_directory(self) -> None:
        shutil.rmtree(self.src / "happy")
        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertEqual([p.name for p in self.root.glob(".*staging")], [])


class IdSafetyTests(_Base):
    def test_an_empty_id_is_refused(self) -> None:
        """It resolves back to the skin root, and the replace branch deletes
        the target recursively — every skin the user has."""

        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, "", home=self.home)

    def test_traversal_and_separators_are_refused(self) -> None:
        for bad in ("../evil", "a/b", "..", "./x", "\\x"):
            with self.subTest(id=bad):
                with self.assertRaises(skininstall.InstallError):
                    skininstall.install(self.src, bad, home=self.home)

    def test_a_dot_prefixed_id_is_refused(self) -> None:
        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, ".hidden", home=self.home)

    def test_an_over_long_id_is_refused(self) -> None:
        with self.assertRaises(skininstall.InstallError):
            skininstall.install(self.src, "x" * 64, home=self.home)

    def test_a_builtin_id_is_refused(self) -> None:
        for bad in ("deepseek", "jellyfish"):
            with self.subTest(id=bad):
                with self.assertRaises(skininstall.InstallError) as caught:
                    skininstall.install(self.src, bad, home=self.home)
                self.assertIn("built-in", str(caught.exception))

    def test_case_variants_are_refused_too(self) -> None:
        """Refused by the character set before the built-in check sees them.

        Both routes matter: the default macOS filesystem is case-insensitive,
        so 'DeepSeek' and 'deepseek' would be one directory. Uppercase never
        gets that far, and the built-in comparison is case-insensitive anyway
        for the day the character set changes.
        """

        for bad in ("DeepSeek", "JELLYFISH", "MyCat"):
            with self.subTest(id=bad):
                with self.assertRaises(skininstall.InstallError):
                    skininstall.install(self.src, bad, home=self.home)
        self.assertFalse((self.root / "DeepSeek").exists())

    def test_frames_from_inside_the_skin_root_are_refused(self) -> None:
        inside = self.root / "staged-elsewhere"
        shutil.copytree(SOURCE, inside)
        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(inside, "mycat", home=self.home)
        self.assertIn("outside the skin root", str(caught.exception))


class EveryFrameTests(_Base):
    """Validation covered a prefix while the copy took the whole tree."""

    def test_a_fourth_undecodable_frame_is_refused(self) -> None:
        """The renderer plays whatever is in the directory, not the first three."""

        (self.src / "idle" / "99.png").write_bytes(b"\xff\xd8\xff garbage" * 40)
        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertIn("99.png", str(caught.exception))

    def test_only_frames_are_copied(self) -> None:
        (self.src / "README-secret.txt").write_text("should not travel", encoding="utf-8")
        path = skininstall.install(self.src, "mycat", home=self.home)
        self.assertFalse((path / "README-secret.txt").exists(),
                         "a skin is a directory people share; only frames belong in it")


class SymlinkTests(_Base):
    def test_installing_through_a_symlink_is_refused(self) -> None:
        """Resolving follows the link, so the check has to precede it.

        Otherwise `alias -> victim` installs over the victim while the caller
        believes it is writing `alias`.
        """

        import os

        victim = self.root / "victim"
        shutil.copytree(SOURCE, victim)
        (victim / skininstall.MARKER).write_text('{"format": 1}', encoding="utf-8")
        before = (victim / "idle" / "00.png").read_bytes()
        os.symlink(victim, self.root / "alias")

        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(self.src, "alias", home=self.home)
        self.assertIn("symlink", str(caught.exception))
        self.assertEqual((victim / "idle" / "00.png").read_bytes(), before,
                         "the victim skin must be untouched")


class ReplaceTests(_Base):
    def test_our_own_install_is_replaced(self) -> None:
        skininstall.install(self.src, "mycat", home=self.home)
        again = skininstall.install(self.src, "mycat", home=self.home, generator="second")
        marker = json.loads((again / skininstall.MARKER).read_text())
        self.assertEqual(marker["generator"], "second")

    def test_a_hand_placed_directory_is_never_overwritten(self) -> None:
        hand = self.root / "mycat"
        shutil.copytree(SOURCE, hand)
        with self.assertRaises(skininstall.InstallError) as caught:
            skininstall.install(self.src, "mycat", home=self.home)
        self.assertIn("by hand", str(caught.exception))
        self.assertTrue((hand / "idle" / "00.png").is_file(), "their files must survive")


class FormatTests(_Base):
    def test_a_newer_format_is_reported_unsupported(self) -> None:
        path = skininstall.install(self.src, "mycat", home=self.home)
        marker = json.loads((path / skininstall.MARKER).read_text())
        marker["format"] = skininstall.FORMAT + 1
        (path / skininstall.MARKER).write_text(json.dumps(marker))
        self.assertFalse(skininstall.is_supported(path))

    def test_a_hand_placed_skin_is_not_version_gated(self) -> None:
        hand = self.root / "handmade"
        shutil.copytree(SOURCE, hand)
        self.assertTrue(skininstall.is_supported(hand))


if __name__ == "__main__":
    unittest.main()
