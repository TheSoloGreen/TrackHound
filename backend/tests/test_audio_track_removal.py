"""Tests for MKV audio track removal planning and execution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.audio_fixer import (
    AudioTrackRemovalError,
    build_keep_audio_track_indices,
    remove_unwanted_audio_tracks,
)


def test_build_keep_audio_track_indices_defaults_to_english_and_undefined():
    tracks = [
        {"index": 0, "language": "ja", "language_raw": "jpn"},
        {"index": 1, "language": "en", "language_raw": "eng"},
        {"index": 2, "language": None, "language_raw": "und"},
        {"index": 3, "language": "es", "language_raw": "spa"},
    ]

    assert build_keep_audio_track_indices(tracks) == [1, 2]


def test_build_keep_audio_track_indices_supports_explicit_user_languages():
    tracks = [
        {"index": 0, "language": "ja", "language_raw": "jpn"},
        {"index": 1, "language": "en", "language_raw": "eng"},
        {"index": 2, "language": None, "language_raw": "und"},
    ]

    assert build_keep_audio_track_indices(tracks, keep_languages=["ja"]) == [0]


def test_remove_unwanted_audio_tracks_uses_mkvmerge_track_ids_and_keeps_backup(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_text("original", encoding="utf-8")
    backup = tmp_path / "movie.mkv.bak"

    tracks = [
        {"index": 0, "language": "ja", "language_raw": "jpn"},
        {"index": 1, "language": "en", "language_raw": "eng"},
        {"index": 2, "language": None, "language_raw": "und"},
    ]
    mkvmerge_probe = {
        "tracks": [
            {"id": 0, "type": "video"},
            {"id": 1, "type": "audio"},
            {"id": 2, "type": "audio"},
            {"id": 3, "type": "subtitles"},
            {"id": 4, "type": "audio"},
        ]
    }

    def fake_run(command, check, capture_output, text):
        if command[:2] == ["mkvmerge", "-J"]:
            class Result:
                stdout = __import__("json").dumps(mkvmerge_probe)
            return Result()
        if command[:3] == ["mkvmerge", "-o", str(source.with_name(".trackhound-movie.mkv"))]:
            Path(command[2]).write_text("remuxed", encoding="utf-8")
            class Result:
                stdout = ""
            return Result()
        raise AssertionError(f"unexpected command: {command}")

    with (
        patch("app.core.audio_fixer.shutil.which", return_value="/usr/bin/mkvmerge"),
        patch("app.core.audio_fixer.subprocess.run", side_effect=fake_run) as run_mock,
    ):
        result = remove_unwanted_audio_tracks(str(source), tracks, keep_track_indices=[1, 2])

    assert result.kept_track_indices == [1, 2]
    assert result.removed_track_indices == [0]
    assert result.backup_path == str(backup)
    assert source.read_text(encoding="utf-8") == "remuxed"
    assert backup.read_text(encoding="utf-8") == "original"

    remux_command = run_mock.call_args_list[1].args[0]
    assert remux_command == [
        "mkvmerge",
        "-o",
        str(source.with_name(".trackhound-movie.mkv")),
        "--audio-tracks",
        "2,4",
        str(source),
    ]


def test_remove_unwanted_audio_tracks_refuses_to_remove_every_audio_track(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_text("original", encoding="utf-8")

    with pytest.raises(AudioTrackRemovalError, match="At least one audio track"):
        remove_unwanted_audio_tracks(str(source), [{"index": 0, "language": "en"}], keep_track_indices=[])
