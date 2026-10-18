"""SQLAlchemy ORM entity models."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, BigInteger, Text, Index, UniqueConstraint, CheckConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Return UTC without an offset for the existing TIMESTAMP columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User account with optional local and Plex credentials."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plex_user_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    plex_username: Mapped[str] = mapped_column(String(255), nullable=False)
    plex_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plex_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plex_thumb_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    last_login: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    username: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def has_local_password(self) -> bool:
        return bool(self.password_hash)

    @property
    def plex_connected(self) -> bool:
        return bool(self.plex_user_id and self.plex_token)

    # Relationships
    preferences: Mapped[list["UserPreference"]] = relationship(
        "UserPreference", back_populates="user", cascade="all, delete-orphan"
    )
    shows: Mapped[list["Show"]] = relationship(
        "Show", back_populates="user", cascade="all, delete-orphan"
    )
    media_files: Mapped[list["MediaFile"]] = relationship(
        "MediaFile", back_populates="user", cascade="all, delete-orphan"
    )
    scan_locations: Mapped[list["ScanLocation"]] = relationship(
        "ScanLocation", back_populates="user", cascade="all, delete-orphan"
    )


class InstanceSettings(Base):
    """One authentication policy and public-mode owner per installation."""
    __tablename__ = "instance_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_instance_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)


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
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    base_media_type: Mapped[str] = mapped_column(String(20), default="tv", nullable=False)
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
    user: Mapped["User"] = relationship("User", back_populates="shows")
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
    __table_args__ = (UniqueConstraint("user_id", "file_path", name="uq_media_files_user_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    show_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("shows.id", ondelete="SET NULL"), nullable=True
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
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
    issue_evaluation_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    analysis_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_policy_revision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    language_review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="media_files")
    show: Mapped[Optional["Show"]] = relationship(
        "Show", back_populates="media_files", foreign_keys=[show_id]
    )
    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="media_files"
    )
    audio_tracks: Mapped[list["AudioTrack"]] = relationship(
        "AudioTrack", back_populates="media_file", cascade="all, delete-orphan"
    )
    issue_records: Mapped[list["MediaIssue"]] = relationship(
        "MediaIssue", cascade="all, delete-orphan", lazy="selectin", order_by="MediaIssue.code"
    )


class MediaIssue(Base):
    """Stable issue codes and evidence, independent of display wording."""

    __tablename__ = "media_issues"
    __table_args__ = (Index("ix_media_issues_code_file", "code", "media_file_id"),)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


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
    __table_args__ = (Index("uq_scan_locations_user_path", "user_id", "path", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
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

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="scan_locations")


class Job(Base):
    """Durable work queue. Payloads contain IDs/options, never credentials."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_status_id", "user_id", "status", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    # A unique nullable reservation prevents duplicate library scans, including queued scans.
    active_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def target_file_id(self) -> Optional[int]:
        return self.payload.get("file_id")

    @property
    def target_show_id(self) -> Optional[int]:
        return self.payload.get("show_id")
