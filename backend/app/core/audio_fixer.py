"""Utilities for updating and pruning MKV audio tracks."""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Lock

from app.core.analyzer import normalize_language

_edit_lock = Lock()
logger = logging.getLogger(__name__)
PROBE_TIMEOUT_SECONDS = 30
DEFAULT_EDIT_TIMEOUT_SECONDS = 60
REMUX_TIMEOUT_SECONDS = 3600


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
    if not _edit_lock.acquire(blocking=False):
        return False
    try:
        return _set_default_track_by_index(file_path, audio_tracks, track_index)
    finally:
        _edit_lock.release()


def _set_default_track_by_index(file_path: str, audio_tracks: list[dict], track_index: int) -> bool:
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
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=DEFAULT_EDIT_TIMEOUT_SECONDS)
        return True
    except (subprocess.SubprocessError, OSError):
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
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as exc:
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
    if valid_track_indices != list(range(len(valid_track_indices))) or len(mkvmerge_audio_ids) != len(valid_track_indices):
        raise AudioTrackRemovalError(
            "The file's audio tracks do not match the stored analysis. Rescan the file first."
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
    """Serialize edits within the single-worker application process."""
    if not _edit_lock.acquire(blocking=False):
        raise AudioTrackRemovalError("Another media edit is in progress. Try again when it finishes.")
    try:
        return _remove_unwanted_audio_tracks(file_path, audio_tracks, keep_track_indices, keep_backup=keep_backup)
    except OSError as exc:
        raise AudioTrackRemovalError("Unable to access the media file, create temporary output, or clean up an edit.") from exc
    finally:
        _edit_lock.release()


def _remove_unwanted_audio_tracks(
    file_path: str,
    audio_tracks: list[dict],
    keep_track_indices: list[int],
    *,
    keep_backup: bool,
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
    source_stat = source.stat()

    kept_indices, removed_indices, kept_mkvmerge_ids = _build_audio_track_id_selection(
        file_path, audio_tracks, keep_track_indices
    )
    if not removed_indices:
        return AudioTrackRemovalResult(
            kept_track_indices=kept_indices,
            removed_track_indices=[],
            backup_path=None,
        )

    backup_path = source.with_suffix(source.suffix + ".bak") if keep_backup else None
    if backup_path and (backup_path.exists() or backup_path.is_symlink()):
        raise AudioTrackRemovalError("A .bak file already exists. Preserve or move that backup before editing again.")
    # Exclusive creation avoids collisions with another run or an existing file.
    fd, temporary_name = tempfile.mkstemp(prefix=".trackhound-", suffix=".mkv", dir=source.parent)
    os.close(fd)
    temporary_output = Path(temporary_name)
    command = [
        "mkvmerge",
        "-o",
        str(temporary_output),
        "--audio-tracks",
        ",".join(str(track_id) for track_id in kept_mkvmerge_ids),
        str(source),
    ]

    backup_reserved = False
    source_moved = False
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=REMUX_TIMEOUT_SECONDS)
        if not temporary_output.stat().st_size or len(_get_mkvmerge_audio_track_ids(str(temporary_output))) != len(kept_indices):
            raise AudioTrackRemovalError("The remuxed file failed verification. The original was retained.")
        current_stat = source.stat()
        if (source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns) != (current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns):
            raise AudioTrackRemovalError("The source file changed during remuxing. Rescan before editing again.")
        shutil.copymode(source, temporary_output)
        if backup_path:
            # Reserve without overwriting any existing backup, including symlinks.
            with backup_path.open("xb"):
                pass
            backup_reserved = True
            source.replace(backup_path)
            source_moved = True
            temporary_output.replace(source)
        else:
            temporary_output.replace(source)
    except subprocess.SubprocessError as exc:
        raise AudioTrackRemovalError("Audio-track removal failed or timed out. The original was retained.") from exc
    except OSError as exc:
        if source_moved and backup_path:
            try:
                if source.exists():
                    raise FileExistsError("A different file now occupies the source path")
                backup_path.replace(source)
            except OSError as restore_error:
                raise AudioTrackRemovalError(
                    f"Replacement and automatic restoration failed. The original is preserved at {backup_path}."
                ) from restore_error
        elif backup_reserved and backup_path:
            backup_path.unlink()
        raise AudioTrackRemovalError("Unable to replace media file. The original was retained or restored.") from exc
    finally:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove remux temporary output: %s", temporary_output)

    return AudioTrackRemovalResult(
        kept_track_indices=kept_indices,
        removed_track_indices=removed_indices,
        backup_path=str(backup_path) if backup_path else None,
    )
