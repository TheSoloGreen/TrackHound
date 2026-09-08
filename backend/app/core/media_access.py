"""Instance policy and live filesystem checks for media mutations."""

import os
from pathlib import Path
import shutil

from app.config import get_settings
from app.models.schemas import MEDIA_ROOT, MediaEditCapabilities


def get_media_edit_capabilities(file_path: str | None = None) -> MediaEditCapabilities:
    """Evaluate capabilities again at write time; UI state is only advisory."""
    reason = None
    parent_writable = True
    if not get_settings().media_writes_enabled:
        reason = "Media editing is disabled by the server administrator."
    elif file_path is not None:
        try:
            path = Path(file_path).resolve(strict=True)
            path.relative_to(MEDIA_ROOT)
            if not path.is_file() or path.suffix.lower() != ".mkv":
                reason = "Only existing MKV files can be edited."
            elif not os.access(path, os.R_OK | os.W_OK):
                reason = "The media file is read-only or inaccessible."
            parent_writable = os.access(path.parent, os.W_OK | os.X_OK)
        except (OSError, ValueError):
            reason = "The file is unavailable or outside the permitted media directory."

    default_reason = reason
    removal_reason = reason
    if reason is None:
        if shutil.which("mkvpropedit") is None:
            default_reason = "The server's default-audio editing tool is unavailable."
        if shutil.which("mkvmerge") is None:
            removal_reason = "The server's audio-track removal tool is unavailable."
        elif not parent_writable:
            removal_reason = "The media directory is read-only or inaccessible."

    return MediaEditCapabilities(
        set_default_audio=default_reason is None,
        remove_audio_tracks=removal_reason is None,
        default_audio_reason=default_reason,
        track_removal_reason=removal_reason,
    )
