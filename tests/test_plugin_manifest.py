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
        self.assertEqual(self.pkg["name"], "dsh-desk-pet")
        self.assertEqual(self.pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertEqual(self.pkg["dsh"]["client"]["platform"], "web")
        self.assertIn("dsh-plugin", self.pkg["keywords"])

    def test_cordis_patch_inserts_the_plugin(self) -> None:
        self.assertIn("id: dsh-desk-pet", _read("cordis.patch.yml"))

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
        self.assertIn("tapIndex", self.plugin)

    def test_serves_state_manifest_and_frames(self) -> None:
        for route in ("/dsh-desk-pet/state", "/dsh-desk-pet/manifest.json", "/dsh-desk-pet/frames/"):
            self.assertIn(route, self.plugin, f"{route} is not served")

    def test_every_registered_route_is_torn_down(self) -> None:
        """A route left registered survives plugin removal and 404s forever."""

        registered = self.plugin.count("ctx.webServer.register(")
        for handle in ("unstate()", "unmanifest()", "unoverlay()", "unframes()", "untap()"):
            self.assertIn(handle, self.plugin, f"{handle} missing from teardown")
        self.assertEqual(registered, 4, "a route was added without a teardown assertion")

    def test_frame_route_refuses_to_escape_the_asset_root(self) -> None:
        self.assertIn("safeJoin", self.plugin)
        self.assertIn("startsWith(prefix)", self.plugin)

    def test_state_route_degrades_instead_of_failing(self) -> None:
        self.assertIn("live: false", self.plugin)


@unittest.skipUnless(NODE, "node not on PATH")
class ParseTests(unittest.TestCase):
    """The plugin is loaded by DSH's Node process, so a syntax error there is
    not a failing test — it is the whole plugin silently not loading."""

    def test_every_shipped_script_parses(self) -> None:
        for name in ("index.mjs", "overlay.js", "client.js"):
            proc = subprocess.run(
                [NODE, "--check", str(ROOT / "plugin" / name)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[:400]}")

    def test_routes_answer_against_a_stand_in_cordis_context(self) -> None:
        """Runs `apply()` for real. Everything else here only reads the source,
        which cannot tell a registered route from one that throws on its first
        request."""

        proc = subprocess.run(
            [NODE, str(ROOT / "tests" / "plugin_smoke.mjs")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-800:])


class OverlayTests(unittest.TestCase):
    def test_overlay_mounts_once_and_uses_real_frames(self) -> None:
        overlay = _read("plugin", "overlay.js")
        self.assertIn("dsh-desk-pet-root", overlay)
        self.assertIn("__dshDeskPetMounted", overlay)
        # Paths are built from a BASE constant, so assert the pieces, not the
        # joined literal — otherwise this passes only by accident of spelling.
        self.assertIn('BASE = "/dsh-desk-pet"', overlay)
        self.assertIn('"/frames/"', overlay)
        self.assertIn('BASE + "/state"', overlay)
        self.assertIn('BASE + "/manifest.json"', overlay)

    def test_overlay_does_not_hand_draw_a_second_pet(self) -> None:
        """The page pet must mirror the desktop one, not re-invent it."""

        overlay = _read("plugin", "overlay.js")
        self.assertNotIn("<ellipse", overlay)
        self.assertNotIn("<svg", overlay)

    def test_client_module_defers_to_the_same_overlay(self) -> None:
        client = _read("plugin", "client.js")
        self.assertIn("__ModuleLoader__", client)
        self.assertIn("/dsh-desk-pet/overlay.js", client)
        self.assertNotIn("<ellipse", client)


if __name__ == "__main__":
    unittest.main()
