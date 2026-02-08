"""Application configuration using Pydantic Settings."""

import logging
import warnings
from functools import lru_cache
from typing import Literal

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
    # SQLite: sqlite+aiosqlite:///./data/cineaudit.db
    # PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = "sqlite+aiosqlite:///./data/cineaudit.db"

    # Security
    secret_key: str = _INSECURE_DEFAULT_KEY
    encryption_key: str = _INSECURE_DEFAULT_ENCRYPTION_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 1 week

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
        if self.secret_key == _INSECURE_DEFAULT_KEY:
            if self.environment == "production":
                raise ValueError(
                    "SECRET_KEY must be set to a secure value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            warnings.warn(
                "Using default SECRET_KEY — set a secure value before deploying. "
                "Generate one with: openssl rand -hex 32",
                stacklevel=2,
            )

        if self.encryption_key == _INSECURE_DEFAULT_ENCRYPTION_KEY:
            if self.environment == "production":
                raise ValueError(
                    "ENCRYPTION_KEY must be set to a secure value in production. "
                    "Generate one with: openssl rand -base64 32"
                )
            warnings.warn(
                "Using default ENCRYPTION_KEY — set a secure value before deploying. "
                "Generate one with: openssl rand -base64 32",
                stacklevel=2,
            )

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
