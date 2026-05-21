"""Utilities for updating and pruning MKV audio tracks."""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess

from app.core.analyzer import normalize_language


class AudioTrackRemovalError(RuntimeError):
    """Raised when an audio track removal request cannot be completed safely."""


@dataclass(frozen=True)
class AudioTrackRemovalResult:
    """Result metadata for an MKV audio track removal operation."""

    kept_track_indices: list[int]
    removed_track_indices: list[int]
    backup_path: str | None


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


def _track_language_tokens(track: dict) -> set[str]:
    """Return normalized language tokens that can match user keep settings."""
    tokens: set[str] = set()
    language = track.get("language")
    language_raw = track.get("language_raw")

    normalized = normalize_language(language)
    if normalized:
        tokens.add(normalized.lower())

    if language_raw:
        raw = str(language_raw).lower().strip()
        tokens.add(raw)
        normalized_raw = normalize_language(raw)
        if normalized_raw:
            tokens.add(normalized_raw.lower())
        elif raw == "und":
            tokens.add("und")
    elif language is None:
        tokens.add("und")

    return tokens


def _normalize_keep_languages(keep_languages: list[str] | None) -> set[str]:
    """Normalize user keep language settings to comparable tokens."""
    if keep_languages is None:
        keep_languages = ["en", "und"]

    normalized: set[str] = set()
    for language in keep_languages:
        raw = (language or "").lower().strip()
        if not raw:
            continue
        if raw == "und":
            normalized.add("und")
            continue
        code = normalize_language(raw)
        if code:
            normalized.add(code.lower())
    return normalized


def build_keep_audio_track_indices(
    audio_tracks: list[dict], keep_languages: list[str] | None = None
) -> list[int]:
    """Select audio track indexes to keep from language settings.

    Defaults are intentionally conservative for TrackHound's main use case:
    keep English plus undefined (`und`) tracks because undefined could be
    English or otherwise valuable until the user reviews it.
    """
    normalized_keep_languages = _normalize_keep_languages(keep_languages)
    keep_indexes: list[int] = []

    for track in sorted(audio_tracks, key=lambda item: item.get("index", 0)):
        track_index = track.get("index")
        if not isinstance(track_index, int):
            continue
        if _track_language_tokens(track) & normalized_keep_languages:
            keep_indexes.append(track_index)

    return keep_indexes


def _get_mkvmerge_audio_track_ids(file_path: str) -> list[int]:
    """Return mkvmerge track IDs for audio tracks, ordered by audio track position."""
    if shutil.which("mkvmerge") is None:
        raise AudioTrackRemovalError("mkvmerge is not installed or not on PATH.")

    try:
        result = subprocess.run(
            ["mkvmerge", "-J", file_path],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AudioTrackRemovalError("Unable to inspect MKV tracks with mkvmerge.") from exc

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioTrackRemovalError("mkvmerge returned invalid JSON while inspecting tracks.") from exc

    audio_track_ids: list[int] = []
    for track in payload.get("tracks", []):
        if track.get("type") == "audio" and isinstance(track.get("id"), int):
            audio_track_ids.append(track["id"])
    return audio_track_ids


def _build_audio_track_id_selection(
    file_path: str, audio_tracks: list[dict], keep_track_indices: list[int]
) -> tuple[list[int], list[int], list[int]]:
    """Map TrackHound audio indexes to mkvmerge track IDs."""
    valid_track_indices = sorted(
        {
            track.get("index")
            for track in audio_tracks
            if isinstance(track.get("index"), int)
        }
    )
    keep_track_indices = sorted(set(keep_track_indices))

    if not keep_track_indices:
        raise AudioTrackRemovalError("At least one audio track must be kept.")

    unknown_indices = sorted(set(keep_track_indices) - set(valid_track_indices))
    if unknown_indices:
        raise AudioTrackRemovalError(
            f"Requested audio track indexes do not exist: {unknown_indices}."
        )

    mkvmerge_audio_ids = _get_mkvmerge_audio_track_ids(file_path)
    if len(mkvmerge_audio_ids) < len(valid_track_indices):
        raise AudioTrackRemovalError(
            "mkvmerge reported fewer audio tracks than TrackHound has stored. Rescan the file first."
        )

    kept_mkvmerge_ids = [mkvmerge_audio_ids[index] for index in keep_track_indices]
    removed_track_indices = [
        index for index in valid_track_indices if index not in keep_track_indices
    ]
    return keep_track_indices, removed_track_indices, kept_mkvmerge_ids


def remove_unwanted_audio_tracks(
    file_path: str,
    audio_tracks: list[dict],
    keep_track_indices: list[int],
    *,
    keep_backup: bool = True,
) -> AudioTrackRemovalResult:
    """Remux an MKV with only the selected audio tracks kept.

    This uses mkvmerge to write a new file next to the source, then replaces the
    source only after mkvmerge succeeds. By default the original file is retained
    as `<filename>.bak` as a fallback.
    """
    source = Path(file_path)
    if source.suffix.lower() != ".mkv":
        raise AudioTrackRemovalError("Audio track removal currently supports MKV files only.")
    if not source.exists():
        raise AudioTrackRemovalError("Media file does not exist on disk.")

    kept_indices, removed_indices, kept_mkvmerge_ids = _build_audio_track_id_selection(
        file_path, audio_tracks, keep_track_indices
    )
    if not removed_indices:
        return AudioTrackRemovalResult(
            kept_track_indices=kept_indices,
            removed_track_indices=[],
            backup_path=None,
        )

    temporary_output = source.with_name(f".trackhound-{source.name}")
    backup_path = source.with_suffix(source.suffix + ".bak") if keep_backup else None
    command = [
        "mkvmerge",
        "-o",
        str(temporary_output),
        "--audio-tracks",
        ",".join(str(track_id) for track_id in kept_mkvmerge_ids),
        str(source),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if keep_backup:
            if backup_path and backup_path.exists():
                backup_path.unlink()
            source.replace(backup_path)
            temporary_output.replace(source)
        else:
            temporary_output.replace(source)
    except subprocess.CalledProcessError as exc:
        if temporary_output.exists():
            temporary_output.unlink()
        raise AudioTrackRemovalError("mkvmerge failed while removing audio tracks.") from exc
    except OSError as exc:
        if temporary_output.exists():
            temporary_output.unlink()
        raise AudioTrackRemovalError("Unable to replace media file after remuxing.") from exc

    return AudioTrackRemovalResult(
        kept_track_indices=kept_indices,
        removed_track_indices=removed_indices,
        backup_path=str(backup_path) if backup_path else None,
    )
