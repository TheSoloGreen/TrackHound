"""Utilities for updating media audio default track flags."""

from pathlib import Path
import shutil
import subprocess


def find_track_index_for_language(audio_tracks: list[dict], language: str) -> int | None:
    """Find the first audio track index matching the requested language."""
    normalized = (language or "").lower().strip()
    for track in audio_tracks:
        track_language = (track.get("language") or "").lower()
        track_index = track.get("index")
        if track_language == normalized and isinstance(track_index, int):
            return track_index
    return None


def set_default_track_by_index(file_path: str, audio_tracks: list[dict], track_index: int) -> bool:
    """Set the provided audio track index as default for an MKV file."""
    if Path(file_path).suffix.lower() != ".mkv":
        return False

    if shutil.which("mkvpropedit") is None:
        return False

    valid_indexes = sorted(
        {
            track.get("index")
            for track in audio_tracks
            if isinstance(track.get("index"), int)
        }
    )
    if track_index not in valid_indexes:
        return False

    command = ["mkvpropedit", file_path]
    for idx in valid_indexes:
        command.extend(["--edit", f"track:a{idx + 1}", "--set", "flag-default=0"])
    command.extend(["--edit", f"track:a{track_index + 1}", "--set", "flag-default=1"])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False


def set_default_track_by_language(file_path: str, audio_tracks: list[dict], language: str) -> bool:
    """Set the first track matching the language as default for an MKV file."""
    target_index = find_track_index_for_language(audio_tracks, language)
    if target_index is None:
        return False
    return set_default_track_by_index(file_path, audio_tracks, target_index)
