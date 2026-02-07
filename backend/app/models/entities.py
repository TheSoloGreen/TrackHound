"""SQLAlchemy ORM entity models."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, BigInteger, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User model for Plex-authenticated users."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plex_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    plex_username: Mapped[str] = mapped_column(String(255), nullable=False)
    plex_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plex_token: Mapped[str] = mapped_column(Text, nullable=False)  # Stored as plaintext — consider encrypting
    plex_thumb_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    last_login: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    preferences: Mapped[list["UserPreference"]] = relationship(
        "UserPreference", back_populates="user", cascade="all, delete-orphan"
    )


class UserPreference(Base):
    """User preferences key-value store."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="preferences")


class Show(Base):
    """Media title model (movie, TV show, or anime)."""

    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(20), default="tv", nullable=False
    )  # tv, movie, anime
    plex_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plex_rating_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_anime: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anime_source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # plex_genre, folder, manual
    thumb_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    seasons: Mapped[list["Season"]] = relationship(
        "Season", back_populates="show", cascade="all, delete-orphan"
    )
    media_files: Mapped[list["MediaFile"]] = relationship(
        "MediaFile",
        back_populates="show",
        foreign_keys="MediaFile.show_id",
        cascade="all, delete-orphan",
    )


class Season(Base):
    """TV season model."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    show_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    plex_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plex_rating_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    show: Mapped["Show"] = relationship("Show", back_populates="seasons")
    media_files: Mapped[list["MediaFile"]] = relationship(
        "MediaFile", back_populates="season", cascade="all, delete-orphan"
    )


class MediaFile(Base):
    """Media file model."""

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    show_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("shows.id", ondelete="SET NULL"), nullable=True
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    episode_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    container_format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_scanned: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    last_modified: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    has_issues: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    issue_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    show: Mapped[Optional["Show"]] = relationship(
        "Show", back_populates="media_files", foreign_keys=[show_id]
    )
    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="media_files"
    )
    audio_tracks: Mapped[list["AudioTrack"]] = relationship(
        "AudioTrack", back_populates="media_file", cascade="all, delete-orphan"
    )


class AudioTrack(Base):
    """Audio track model."""

    __tablename__ = "audio_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False
    )
    track_index: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # Normalized to ISO 639-1
    language_raw: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # Original from file
    codec: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    channels: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel_layout: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bitrate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_forced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    media_file: Mapped["MediaFile"] = relationship(
        "MediaFile", back_populates="audio_tracks"
    )


class ScanLocation(Base):
    """Scan location configuration."""

    __tablename__ = "scan_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(20), default="tv", nullable=False
    )  # tv, movie, anime
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scanned: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
