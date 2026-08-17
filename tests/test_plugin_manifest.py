"""The shipped package must be a discoverable DSH bundle that carries its art.

These are cheap string assertions, but each one stands for a way the plugin has
already been able to install successfully and still show nothing: art excluded
from the tarball, a route dropped on teardown, or a second hand-drawn pet
quietly diverging from the real one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class PackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pkg = json.loads(_read("package.json"))

    def test_identifies_as_a_dsh_bundle(self) -> None:
        self.assertEqual(self.pkg["name"], "deepseek-desk-pet")
        self.assertEqual(self.pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertIn("dsh-plugin", self.pkg["keywords"])
        # Deliberately no `dsh.client`: this plugin has no page-side half.
        # ShippedSurfaceTests asserts that absence with the reason attached.

    def test_cordis_patch_imports_the_published_package_name(self) -> None:
        """The patch entry's `name` is the module specifier DSH imports, so it
        must be the npm name rather than the repo name. Those differ here: npm
        rejected `dsh-desk-pet` as too similar to an unrelated `dsh-deskpet`, so
        a patch naming the repo would resolve to nothing on a fresh install."""

        patch = _read("cordis.patch.yml")
        self.assertIn(f'name: {self.pkg["name"]}', patch)

    def test_published_files_include_the_art(self) -> None:
        """Installing and getting a pet with no frames is the old bug.

        Checks the PNG tree and the manifest specifically. The GIF tree is
        deliberately not shipped: every renderer call site passes web=True, so
        the GIFs are left over from the Tk path and were a quarter of the
        download. If a GIF reader ever comes back, this is the test to change.
        """

        files = self.pkg["files"]
        self.assertIn("assets/web", files, "the frames the renderer plays would not ship")
        self.assertIn(
            "assets/skins/manifest.json", files,
            "the manifest carries frame timings and subject boxes",
        )

    def test_every_shipped_skin_is_covered_by_the_published_files(self) -> None:
        """A skin the catalog offers but the tarball omits is a broken install."""

        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from dsh_desk_pet import skins

        covered = set(self.pkg["files"])
        for skin in skins.BUILTIN_SKINS:
            frames = ROOT / "assets" / "web" / skin.id
            self.assertTrue(frames.is_dir(), f"{skin.id} has no frames on disk")
            # 'assets/web' covers every skin under it; spelled out so a future
            # narrowing of `files` to individual skins still has to pass here.
            self.assertTrue(
                "assets/web" in covered or f"assets/web/{skin.id}" in covered,
                f"{skin.id} is selectable but would not ship",
            )

    def test_published_files_exclude_the_chroma_key_sources(self) -> None:
        """`assets/source` is build input; shipping it doubles the download."""

        self.assertNotIn("assets", self.pkg["files"])
        self.assertNotIn("assets/source", self.pkg["files"])


class HostPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = _read("plugin", "index.mjs")

    def test_exports_the_cordis_surface(self) -> None:
        self.assertIn("export function apply", self.plugin)
        self.assertIn("export const name = 'dsh-desk-pet'", self.plugin)

    def test_launches_the_desktop_pet(self) -> None:
        self.assertIn("spawn(", self.plugin)
        self.assertIn("bin", self.plugin)

    def test_serves_nothing_to_the_page(self) -> None:
        """The in-page pet is gone on purpose; two pets read as a bug.

        Asserted as an absence because that is what keeps it gone: the mirror
        was where the failures lived, and adding a route back would quietly
        recreate the surface that produced them.
        """

        for gone in ("webServer.register", "tapIndex", "overlay", "/frames"):
            self.assertNotIn(gone, self.plugin, f"{gone} puts a pet back in the page")

    def test_gates_on_the_web_server_without_using_it(self) -> None:
        """The injection is a gate, not a dependency.

        It keeps a window from appearing during a headless or scheduled run,
        where a pet popping onto the screen would be a fault rather than a
        feature. Removing the injection is what would break that.
        """

        self.assertIn("export const inject = ['webServer']", self.plugin)

    def test_reports_why_the_pet_died(self) -> None:
        """A pet that silently fails to appear is indistinguishable from one
        that is merely invisible, which cost real debugging time."""

        self.assertIn("stdio: ['ignore', 'pipe', 'pipe']", self.plugin)
        self.assertIn("desktop companion exited", self.plugin)

    def test_stops_the_pet_on_teardown(self) -> None:
        self.assertIn("ctx.effect(", self.plugin)
        self.assertIn("child.kill()", self.plugin)


class ShippedSurfaceTests(unittest.TestCase):
    def test_the_page_side_files_are_gone(self) -> None:
        for name in ("overlay.js", "client.js"):
            self.assertFalse(
                (ROOT / "plugin" / name).exists(),
                f"plugin/{name} came back; the page pet was removed deliberately",
            )

    def test_the_manifest_no_longer_advertises_a_client(self) -> None:
        pkg = json.loads(_read("package.json"))
        self.assertNotIn("client", pkg["dsh"], "DSH would look for a client module")
        self.assertNotIn("./client", pkg["exports"])

    def test_the_frames_the_renderer_plays_still_ship(self) -> None:
        """`assets/web` is named for a surface that no longer exists, but it is
        the tree the desktop renderer reads — every call site passes web=True.
        Deleting it while removing 'the web pet' would delete all the art."""

        pkg = json.loads(_read("package.json"))
        self.assertIn("assets/web", pkg["files"])
        self.assertTrue((ROOT / "assets" / "web" / "deepseek" / "idle" / "00.png").is_file())


@unittest.skipUnless(NODE, "node not on PATH")
class ParseTests(unittest.TestCase):
    """The plugin is loaded by DSH's Node process, so a syntax error there is
    not a failing test — it is the whole plugin silently not loading."""

    def test_every_shipped_script_parses(self) -> None:
        for name in ("index.mjs",):
            proc = subprocess.run(
                [NODE, "--check", str(ROOT / "plugin" / name)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[:400]}")

    def test_applies_against_a_stand_in_cordis_context(self) -> None:
        """Runs `apply()` for real. Everything else here only reads the source,
        which cannot tell a plugin that loads from one that throws on apply."""

        proc = subprocess.run(
            [NODE, str(ROOT / "tests" / "plugin_smoke.mjs")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
