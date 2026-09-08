"""Application configuration using Pydantic Settings."""

import logging
import warnings
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_INSECURE_DEFAULT_KEY = "change-me-in-production-use-openssl-rand-hex-32"
_INSECURE_DEFAULT_ENCRYPTION_KEY = "change-me-trackhound-encryption-key"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "TrackHound"
    debug: bool = False
    environment: Literal["development", "production", "test"] = "development"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database - supports both SQLite and PostgreSQL
    # SQLite: sqlite+aiosqlite:///./data/trackhound.db
    # PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = "sqlite+aiosqlite:///./data/trackhound.db"

    # Security
    secret_key: str = _INSECURE_DEFAULT_KEY
    encryption_key: str = _INSECURE_DEFAULT_ENCRYPTION_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 1 week
    allowed_plex_user_ids: str = ""
    media_writes_enabled: bool = False

    # Plex OAuth
    plex_client_identifier: str = "trackhound"
    plex_product: str = "TrackHound"
    plex_version: str = "1.0.0"
    plex_platform: str = "Web"
    plex_device_name: str = "TrackHound"

    # CORS - comma-separated list of allowed origins
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    def validate_secret_key(self) -> None:
        """Warn or raise if the secret key is insecure."""
        if self.secret_key == _INSECURE_DEFAULT_KEY or len(self.secret_key.strip()) < 32:
            if self.environment == "production":
                raise ValueError(
                    "SECRET_KEY must be a non-default value of at least 32 characters in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            warnings.warn(
                "Using default or short SECRET_KEY — set a secure value before deploying. "
                "Generate one with: openssl rand -hex 32",
                stacklevel=2,
            )

        if self.encryption_key == _INSECURE_DEFAULT_ENCRYPTION_KEY or len(self.encryption_key.strip()) < 32:
            if self.environment == "production":
                raise ValueError(
                    "ENCRYPTION_KEY must be a non-default value of at least 32 characters in production. "
                    "Generate one with: openssl rand -base64 32"
                )
            warnings.warn(
                "Using default or short ENCRYPTION_KEY — set a secure value before deploying. "
                "Generate one with: openssl rand -base64 32",
                stacklevel=2,
            )

    @field_validator("allowed_plex_user_ids")
    @classmethod
    def validate_allowed_plex_user_ids(cls, value: str) -> str:
        ids = [item.strip() for item in value.split(",") if item.strip()]
        if any(not item.isascii() or not item.isdecimal() or int(item) <= 0 for item in ids):
            raise ValueError("ALLOWED_PLEX_USER_IDS must contain comma-separated positive numeric Plex account IDs")
        return ",".join(dict.fromkeys(str(int(item)) for item in ids))

    @property
    def allowed_plex_user_ids_set(self) -> set[str]:
        """An empty allowlist deliberately grants no account access."""
        return set(filter(None, self.allowed_plex_user_ids.split(",")))

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list, filtering empty strings."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        """Check if using PostgreSQL database."""
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.validate_secret_key()
    return settings
