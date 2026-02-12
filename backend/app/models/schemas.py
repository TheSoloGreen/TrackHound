"""Pydantic schemas for API request/response models."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


MEDIA_ROOT = Path("/media").resolve()


class ScanMediaType(str, Enum):
    """Allowed scan media types."""

    TV = "tv"
    MOVIE = "movie"
    ANIME = "anime"


def validate_media_root_path(path: str) -> str:
    """Validate a normalized absolute path that must stay under /media."""
    try:
        resolved = Path(path).resolve()
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("Path is invalid. Provide an absolute, normalized path under /media.") from exc

    if not resolved.is_absolute():
        raise ValueError("Path must be absolute and under /media.")

    try:
        resolved.relative_to(MEDIA_ROOT)
    except ValueError as exc:
        raise ValueError("Path must be under /media.") from exc

    normalized = str(resolved)
    if path != normalized:
        raise ValueError(f"Path must be normalized. Use '{normalized}'.")

    return normalized


# ============== Auth Schemas ==============


class PlexPinResponse(BaseModel):
    """Response when initiating Plex OAuth."""

    pin_id: int
    pin_code: str
    auth_url: str


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User information response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    plex_username: str
    plex_email: Optional[str] = None
    plex_thumb_url: Optional[str] = None
    created_at: datetime
    last_login: datetime


# ============== Scan Location Schemas ==============


class ScanLocationCreate(BaseModel):
    """Create a new scan location."""

    path: str
    label: str
    media_type: ScanMediaType = ScanMediaType.TV
    enabled: bool = True

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Require normalized scan locations under /media."""
        return validate_media_root_path(value)


class ScanLocationUpdate(BaseModel):
    """Update an existing scan location."""

    label: Optional[str] = None
    media_type: Optional[ScanMediaType] = None
    enabled: Optional[bool] = None


class ScanLocationResponse(BaseModel):
    """Scan location response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    label: str
    media_type: str
    enabled: bool
    last_scanned: Optional[datetime] = None
    file_count: int
    created_at: datetime


class DirectoryEntry(BaseModel):
    """A directory entry for browsing."""

    name: str
    path: str


class DirectoryBrowseResponse(BaseModel):
    """Response from directory browse endpoint."""

    current_path: str
    directories: list[DirectoryEntry]


# ============== Scan Schemas ==============


class ScanStatus(BaseModel):
    """Current scan status."""

    is_running: bool
    current_location: Optional[str] = None
    files_scanned: int = 0
    files_total: int = 0
    current_file: Optional[str] = None
    started_at: Optional[datetime] = None
    errors: list[str] = Field(default_factory=list)


class ScanStartRequest(BaseModel):
    """Request to start a scan."""

    location_ids: Optional[list[int]] = None  # None = scan all enabled locations
    incremental: bool = True  # Only scan new/modified files


# ============== Audio Track Schemas ==============


class AudioTrackResponse(BaseModel):
    """Audio track information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    track_index: int
    language: Optional[str] = None
    language_raw: Optional[str] = None
    codec: Optional[str] = None
    channels: Optional[int] = None
    channel_layout: Optional[str] = None
    bitrate: Optional[int] = None
    is_default: bool
    is_forced: bool
    title: Optional[str] = None


# ============== Media File Schemas ==============


class MediaFileResponse(BaseModel):
    """Media file information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    filename: str
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    file_size: int
    container_format: Optional[str] = None
    duration_ms: Optional[int] = None
    last_scanned: datetime
    has_issues: bool
    issue_details: Optional[str] = None
    audio_tracks: list[AudioTrackResponse] = []


class MediaFileListResponse(BaseModel):
    """Paginated media file list."""

    items: list[MediaFileResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ============== Season Schemas ==============


class SeasonResponse(BaseModel):
    """Season information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    season_number: int
    episode_count: int = 0
    issues_count: int = 0


class SeasonDetailResponse(SeasonResponse):
    """Season with episodes."""

    media_files: list[MediaFileResponse] = []


# ============== Show Schemas ==============


class ShowResponse(BaseModel):
    """Show information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    media_type: str = "tv"
    is_anime: bool
    anime_source: Optional[str] = None
    thumb_url: Optional[str] = None
    season_count: int = 0
    episode_count: int = 0
    file_count: int = 0
    issues_count: int = 0
    created_at: datetime
    updated_at: datetime


class ShowDetailResponse(ShowResponse):
    """Show with seasons and direct files (for movies)."""

    seasons: list[SeasonResponse] = []
    media_files: list[MediaFileResponse] = []


class ShowUpdate(BaseModel):
    """Update show properties."""

    media_type: Optional[str] = None
    is_anime: Optional[bool] = None
    anime_source: Optional[str] = None


class ShowListResponse(BaseModel):
    """Paginated show list."""

    items: list[ShowResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ============== Settings Schemas ==============


class AudioPreferences(BaseModel):
    """Audio preference rules."""

    require_english_non_anime: bool = True
    require_japanese_anime: bool = True
    require_dual_audio_anime: bool = True
    check_default_track: bool = True
    preferred_codecs: list[str] = []  # Empty = no preference
    auto_fix_english_default_non_anime: bool = False


class AnimeDetectionSettings(BaseModel):
    """Anime detection configuration."""

    use_plex_genres: bool = True
    anime_folder_keywords: list[str] = ["anime", "animation"]


class UserSettingsResponse(BaseModel):
    """User settings response."""

    audio_preferences: AudioPreferences
    anime_detection: AnimeDetectionSettings
    file_extensions: list[str] = [".mkv", ".mp4", ".avi", ".m4v"]


class UserSettingsUpdate(BaseModel):
    """Update user settings."""

    audio_preferences: Optional[AudioPreferences] = None
    anime_detection: Optional[AnimeDetectionSettings] = None
    file_extensions: Optional[list[str]] = None


class UpdateDefaultAudioRequest(BaseModel):
    """Request to set a media file default audio track by language."""

    language: str = Field(min_length=2, max_length=10)


class UpdateDefaultAudioResponse(BaseModel):
    """Response after applying a default audio update."""

    message: str
    media_file: MediaFileResponse


# ============== Stats Schemas ==============


class DashboardStats(BaseModel):
    """Dashboard statistics."""

    total_titles: int
    total_files: int
    total_files_with_issues: int
    movie_count: int
    tv_count: int
    anime_count: int
    missing_english_count: int
    missing_japanese_count: int
    missing_dual_audio_count: int
    last_scan: Optional[datetime] = None
