"""The shipped package must be a discoverable DSH bundle."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class PluginManifestTests(unittest.TestCase):
    def test_bundle_patch_and_apply_export_exist(self) -> None:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["name"], "dsh-desk-pet")
        self.assertEqual(pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertEqual(pkg["dsh"]["client"]["platform"], "web")
        self.assertTrue((ROOT / "plugin" / "client.js").is_file())
        client = (ROOT / "plugin" / "client.js").read_text(encoding="utf-8")
        self.assertIn("__ModuleLoader__", client)
        self.assertIn("dsh-desk-pet-root", client)
        self.assertTrue((ROOT / "cordis.patch.yml").is_file())
        patch = (ROOT / "cordis.patch.yml").read_text(encoding="utf-8")
        self.assertIn("id: dsh-desk-pet", patch)
        plugin = (ROOT / "plugin" / "index.mjs").read_text(encoding="utf-8")
        self.assertIn("export function apply", plugin)
        self.assertIn("export const name = 'dsh-desk-pet'", plugin)
        self.assertIn("LAUNCHER", plugin)
        self.assertIn("dsh-plugin", pkg["keywords"])
