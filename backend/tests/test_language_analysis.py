from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from app.core.analyzer import AudioAnalyzer, normalize_language, infer_language_from_title


@pytest.mark.parametrize("value,expected", [("en-US", "en"), ("ENG_us", "en"),
    ("zh-Hant-TW", "zh"), ("ja-JP", "ja"), ("und-US", None), ("not-a-language", None)])
def test_primary_language_normalization(value, expected):
    assert normalize_language(value) == expected


@pytest.mark.parametrize("title,expected", [
    ("Dolby Digital 5.1", None), ("Spanish 5.1", "es"), ("English commentary", "en"),
    ("JPN_2.0", "ja"), ("[en] Main", "en"), ("It is original audio", None),
    ("It", None), ("No", None),
    ("English / Japanese", None), ("[en] Japanese", None), ("Original Audio", None),
])
def test_title_hints_require_explicit_unambiguous_language(title, expected):
    assert infer_language_from_title(title) == expected


def test_analyzer_retains_raw_evidence_and_prefers_embedded_language():
    tracks = [NS(track_type="Audio", language=language, other_language=None, title=title,
                 channel_s=6, channel_layout=None, bit_rate=None, format="AC-3", default="Yes", forced="No")
              for language, title in [(None, "Dolby Digital 5.1"), ("ja-JP", "English")]]
    analyzer = AudioAnalyzer()
    analyzer._mediainfo_available = True
    with patch("pymediainfo.MediaInfo.parse", return_value=NS(tracks=tracks)):
        result = analyzer.analyze("/synthetic.mkv")
    first, second = result["audio_tracks"]
    assert first["language"] is None and first["title"] == "Dolby Digital 5.1"
    assert second["language"] == "ja" and second["language_raw"] == "ja-JP"
