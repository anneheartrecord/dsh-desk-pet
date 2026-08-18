"""The update check. Never reaches the network: the opener is injected."""

from __future__ import annotations

import io
import json
import unittest

from dsh_desk_pet import updates


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload, *, raises=None):
    def open_it(url, timeout=None):
        open_it.url = url
        if raises is not None:
            raise raises
        return _Response(json.dumps(payload).encode())

    open_it.url = ""
    return open_it


class VersionTests(unittest.TestCase):
    def test_orders_by_number_not_by_string(self) -> None:
        self.assertTrue(updates.is_newer("0.10.0", "0.9.0"))
        self.assertFalse(updates.is_newer("0.9.0", "0.10.0"))

    def test_equal_is_not_newer(self) -> None:
        self.assertFalse(updates.is_newer("1.2.3", "1.2.3"))

    def test_unparseable_version_is_never_newer(self) -> None:
        self.assertFalse(updates.is_newer("main", "0.1.0"))
        self.assertFalse(updates.is_newer("0.2.0", "main"))


class QueryTests(unittest.TestCase):
    def test_queries_the_manifest_name_not_a_literal(self) -> None:
        """The npm package and the repo have different names on purpose.

        npm refused the repo's name as too similar to an unrelated package, so
        a hard-coded string would query the wrong one.
        """

        opener = _opener({"version": "9.9.9"})
        updates.fetch_published(updates.package_name(), opener=opener)
        self.assertIn(updates.package_name(), opener.url)
        self.assertEqual(updates.package_name(), "deepseek-desk-pet")

    def test_request_is_https(self) -> None:
        opener = _opener({"version": "9.9.9"})
        updates.fetch_published("x", opener=opener)
        self.assertTrue(opener.url.startswith("https://"))

    def test_connection_error_reports_unknown_not_current(self) -> None:
        opener = _opener(None, raises=OSError("no route to host"))
        self.assertIsNone(updates.fetch_published("x", opener=opener))

    def test_a_404_reports_unknown_not_current(self) -> None:
        opener = _opener(None, raises=Exception("HTTP Error 404"))
        self.assertIsNone(updates.fetch_published("x", opener=opener))

    def test_non_semver_published_version_is_refused(self) -> None:
        self.assertIsNone(updates.fetch_published("x", opener=_opener({"version": "latest"})))

    def test_over_long_version_is_refused(self) -> None:
        self.assertIsNone(updates.fetch_published("x", opener=_opener({"version": "9" * 500})))

    def test_missing_version_field_is_refused(self) -> None:
        self.assertIsNone(updates.fetch_published("x", opener=_opener({})))


class LabelTests(unittest.TestCase):
    def test_newer_version_names_it_and_the_upgrade_command(self) -> None:
        """The pet cannot update itself, so a bare version leaves the user guessing."""

        text = updates.label("0.1.0", "0.2.0", upgrade_hint="dsh plugin add deepseek-desk-pet")
        self.assertIn("0.2.0", text)
        self.assertIn("dsh plugin add", text)

    def test_equal_version_reads_up_to_date(self) -> None:
        self.assertEqual(updates.label("0.1.0", "0.1.0"), "Up to date")

    def test_unknown_result_does_not_claim_up_to_date(self) -> None:
        self.assertNotIn("Up to date", updates.label("0.1.0", None))

    def test_branch_build_reports_neutrally(self) -> None:
        """A #main install would otherwise read as permanently behind."""

        self.assertEqual(updates.label("main", "0.2.0"), "Check for Updates")


if __name__ == "__main__":
    unittest.main()
