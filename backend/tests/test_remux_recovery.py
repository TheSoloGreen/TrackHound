"""Exercise remux failures using isolated files and injected filesystem errors."""

from pathlib import Path
from unittest.mock import patch
import subprocess

import pytest

from app.core import audio_fixer

TRACKS = [{"index": 0, "language": "en"}, {"index": 1, "language": "ja"}]


@pytest.fixture
def remux(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"original")
    backup = source.with_suffix(".mkv.bak")

    def probe(path):
        return [1, 2] if Path(path) == source else [1]

    def run(command, **kwargs):
        Path(command[2]).write_bytes(b"verified remux")

    with (
        patch.object(audio_fixer, "_get_mkvmerge_audio_track_ids", side_effect=probe),
        patch.object(audio_fixer.subprocess, "run", side_effect=run) as command,
    ):
        yield source, backup, command


def test_existing_backup_is_never_overwritten(remux):
    source, backup, command = remux
    backup.write_bytes(b"earlier original")
    with pytest.raises(audio_fixer.AudioTrackRemovalError, match="already exists"):
        audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert source.read_bytes() == b"original"
    assert backup.read_bytes() == b"earlier original"
    command.assert_not_called()


def test_failed_final_rename_restores_original_path(remux, monkeypatch):
    source, backup, _ = remux
    replace = Path.replace

    def fail_install(path, target):
        if path.name.startswith(".trackhound-"):
            raise OSError("injected final rename failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_install)
    with pytest.raises(audio_fixer.AudioTrackRemovalError, match="restored"):
        audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert source.read_bytes() == b"original"
    assert not backup.exists()
    assert not list(source.parent.glob(".trackhound-*.mkv"))


def test_failed_restoration_preserves_backup_and_reports_recovery_path(remux, monkeypatch):
    source, backup, _ = remux
    replace = Path.replace

    def fail_install_and_restore(path, target):
        if path.name.startswith(".trackhound-") or path == backup:
            raise OSError("injected failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_install_and_restore)
    with pytest.raises(audio_fixer.AudioTrackRemovalError, match=str(backup)):
        audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert backup.read_bytes() == b"original"
    assert not source.exists()


def test_remux_timeout_leaves_original_and_cleans_temporary_output(remux):
    source, backup, command = remux
    command.side_effect = subprocess.TimeoutExpired("mkvmerge", 3600)
    with pytest.raises(audio_fixer.AudioTrackRemovalError, match="timed out"):
        audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert source.read_bytes() == b"original"
    assert not backup.exists()
    assert not list(source.parent.glob(".trackhound-*.mkv"))


def test_invalid_remux_output_never_replaces_source(remux):
    source, backup, _ = remux
    with patch.object(audio_fixer, "_get_mkvmerge_audio_track_ids", return_value=[1, 2]):
        with pytest.raises(audio_fixer.AudioTrackRemovalError, match="failed verification"):
            audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert source.read_bytes() == b"original"
    assert not backup.exists()


def test_concurrently_changed_source_is_not_replaced(remux):
    source, backup, command = remux

    def run(command, **kwargs):
        Path(command[2]).write_bytes(b"remux result")
        source.write_bytes(b"another process replaced the media")

    command.side_effect = run
    with pytest.raises(audio_fixer.AudioTrackRemovalError, match="changed during"):
        audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    assert source.read_bytes() == b"another process replaced the media"
    assert not backup.exists()


def test_concurrent_edit_is_rejected(remux):
    source, _, command = remux
    with audio_fixer._edit_lock:
        with pytest.raises(audio_fixer.AudioTrackRemovalError, match="in progress"):
            audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
        assert not audio_fixer.set_default_track_by_index(str(source), TRACKS, 0)
    command.assert_not_called()


def test_audio_count_change_requires_rescan(remux):
    source, _, command = remux
    with patch.object(audio_fixer, "_get_mkvmerge_audio_track_ids", return_value=[1, 2, 3]):
        with pytest.raises(audio_fixer.AudioTrackRemovalError, match="do not match"):
            audio_fixer.remove_unwanted_audio_tracks(str(source), TRACKS, [0])
    command.assert_not_called()
