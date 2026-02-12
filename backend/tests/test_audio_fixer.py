"""Tests for low-level audio default fixer utilities."""

import unittest
from unittest.mock import patch

from app.core.audio_fixer import (
    find_track_index_for_language,
    set_default_track_by_index,
)


class AudioFixerTests(unittest.TestCase):
    def test_find_track_index_for_language(self):
        tracks = [
            {"index": 0, "language": "ja"},
            {"index": 1, "language": "en"},
        ]

        self.assertEqual(find_track_index_for_language(tracks, "en"), 1)
        self.assertIsNone(find_track_index_for_language(tracks, "fr"))

    def test_set_default_track_by_index_builds_command(self):
        tracks = [
            {"index": 0, "language": "ja"},
            {"index": 1, "language": "en"},
        ]

        with (
            patch("app.core.audio_fixer.shutil.which", return_value="/usr/bin/mkvpropedit"),
            patch("app.core.audio_fixer.subprocess.run") as run_mock,
        ):
            ok = set_default_track_by_index("/media/movie/file.mkv", tracks, 1)

        self.assertTrue(ok)
        command = run_mock.call_args.args[0]
        self.assertIn("track:a1", command)
        self.assertIn("track:a2", command)


if __name__ == "__main__":
    unittest.main()
