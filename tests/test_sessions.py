"""Reading the local DSH session list.

The panel is built entirely from what the filesystem gives away, so these tests
build real session directories in a temp home rather than mocking anything.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from dsh_desk_pet import sessions


class DecodeCwdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_plain_path_round_trips(self) -> None:
        self.assertEqual(sessions.decode_cwd("--private-tmp-x--"), Path("/private/tmp/x"))

    def test_a_dash_in_a_real_folder_name_is_not_a_separator(self) -> None:
        """`deepseek-harness` must not decode to `deepseek/harness`.

        Nothing in the encoding distinguishes the two; only the filesystem can.
        """

        real = self.base / "my-project"
        real.mkdir()
        encoded = "--" + str(real).strip("/").replace("/", "-") + "--"
        self.assertEqual(sessions.decode_cwd(encoded), real)

    def test_a_path_that_no_longer_exists_still_decodes(self) -> None:
        decoded = sessions.decode_cwd("--Users-nobody-gone-away--")
        self.assertEqual(decoded, Path("/Users/nobody/gone/away"))

    def test_empty_name_is_root(self) -> None:
        self.assertEqual(sessions.decode_cwd("----"), Path("/"))


class ListSessionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def _session(self, project: str, name: str, *, age_s: float = 0.0) -> Path:
        directory = self.home / "sessions" / project / name
        directory.mkdir(parents=True)
        log = directory / "session.jsonl.zstd"
        log.write_bytes(b"not really zstd")
        stamp = time.time() - age_s
        import os

        os.utime(log, (stamp, stamp))
        return directory

    def test_no_sessions_directory_is_empty_not_an_error(self) -> None:
        self.assertEqual(sessions.list_sessions(self.home), [])

    def test_most_recent_first(self) -> None:
        self._session("--a--", "session-old", age_s=3600)
        self._session("--a--", "session-new", age_s=5)
        rows = sessions.list_sessions(self.home, titles=False)
        self.assertEqual([r.session_id for r in rows], ["session-new", "session-old"])

    def test_limit_is_respected(self) -> None:
        for index in range(8):
            self._session("--a--", f"session-{index}", age_s=index)
        self.assertEqual(len(sessions.list_sessions(self.home, limit=3, titles=False)), 3)

    def test_recent_activity_reads_as_active(self) -> None:
        self._session("--a--", "session-live", age_s=1)
        self._session("--a--", "session-cold", age_s=600)
        rows = {r.session_id: r.active for r in sessions.list_sessions(self.home, titles=False)}
        self.assertTrue(rows["session-live"])
        self.assertFalse(rows["session-cold"])

    def test_title_falls_back_to_the_project_folder(self) -> None:
        """No zstd binary, or an unreadable log, must still label the row."""

        self._session("--private-tmp-demo--", "session-x")
        row = sessions.list_sessions(self.home, titles=False)[0]
        self.assertEqual(row.title, "demo")

    def test_total_counts_every_session_not_just_the_shown_ones(self) -> None:
        for index in range(5):
            self._session("--a--", f"session-{index}")
        for index in range(2):
            self._session("--b--", f"session-b{index}")
        self.assertEqual(sessions.total_count(self.home), 7)

    def test_unreadable_project_directory_is_skipped(self) -> None:
        self._session("--a--", "session-ok")
        (self.home / "sessions" / "loose-file").write_text("x", encoding="utf-8")
        self.assertEqual(len(sessions.list_sessions(self.home, titles=False)), 1)


class AgeLabelTests(unittest.TestCase):
    def _row(self, age_s: float) -> sessions.Session:
        now = time.time()
        return sessions.Session("s", Path("/tmp"), "t", now - age_s, False)

    def test_labels_read_the_way_a_person_would_say_them(self) -> None:
        self.assertEqual(self._row(2).age_label(), "just now")
        self.assertEqual(self._row(45).age_label(), "45s ago")
        self.assertEqual(self._row(600).age_label(), "10m ago")
        self.assertEqual(self._row(7200).age_label(), "2h ago")
        self.assertEqual(self._row(3 * 86400).age_label(), "3d ago")


if __name__ == "__main__":
    unittest.main()
