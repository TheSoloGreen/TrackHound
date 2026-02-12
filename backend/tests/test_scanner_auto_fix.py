"""Tests for automatic default track fixing in scanner."""

import unittest
from unittest.mock import MagicMock, patch

from app.core.preference_engine import AudioPreferences
from app.core.scanner import MediaScanner


class MediaScannerAutoFixTests(unittest.TestCase):
    def setUp(self):
        self.scanner = MediaScanner(
            audio_preferences=AudioPreferences(auto_fix_english_default_non_anime=True)
        )

    def test_get_english_default_fix_index_returns_none_when_english_already_default(self):
        tracks = [
            {"index": 0, "language": "en", "is_default": True},
            {"index": 1, "language": "ja", "is_default": False},
        ]

        index = self.scanner._get_english_default_fix_index(tracks)

        self.assertIsNone(index)

    def test_get_english_default_fix_index_returns_english_track_when_non_english_default(self):
        tracks = [
            {"index": 0, "language": "ja", "is_default": True},
            {"index": 1, "language": "en", "is_default": False},
        ]

        index = self.scanner._get_english_default_fix_index(tracks)

        self.assertEqual(index, 1)

    def test_auto_fix_skips_when_setting_disabled(self):
        scanner = MediaScanner(
            audio_preferences=AudioPreferences(auto_fix_english_default_non_anime=False)
        )
        audio_info = {
            "audio_tracks": [
                {"index": 0, "language": "ja", "is_default": True},
                {"index": 1, "language": "en", "is_default": False},
            ]
        }

        with patch("app.core.scanner.set_default_track_by_index") as set_default_mock:
            result = scanner._auto_fix_default_track(
                "/media/movies/file.mkv", audio_info, is_anime=False
            )

        self.assertEqual(result, audio_info)
        set_default_mock.assert_not_called()

    def test_auto_fix_skips_anime(self):
        audio_info = {
            "audio_tracks": [
                {"index": 0, "language": "ja", "is_default": True},
                {"index": 1, "language": "en", "is_default": False},
            ]
        }

        with patch("app.core.scanner.set_default_track_by_index") as set_default_mock:
            result = self.scanner._auto_fix_default_track(
                "/media/anime/episode.mkv", audio_info, is_anime=True
            )

        self.assertEqual(result, audio_info)
        set_default_mock.assert_not_called()

    def test_auto_fix_uses_audio_fixer_and_reanalyzes(self):
        audio_info = {
            "audio_tracks": [
                {"index": 0, "language": "ja", "is_default": True},
                {"index": 1, "language": "en", "is_default": False},
            ]
        }
        refreshed_info = {
            "audio_tracks": [
                {"index": 0, "language": "ja", "is_default": False},
                {"index": 1, "language": "en", "is_default": True},
            ]
        }

        self.scanner.analyzer.analyze = MagicMock(return_value=refreshed_info)

        with patch("app.core.scanner.set_default_track_by_index", return_value=True) as fix_mock:
            result = self.scanner._auto_fix_default_track(
                "/media/movies/file.mkv", audio_info, is_anime=False
            )

        self.assertEqual(result, refreshed_info)
        fix_mock.assert_called_once_with("/media/movies/file.mkv", audio_info["audio_tracks"], 1)


if __name__ == "__main__":
    unittest.main()
