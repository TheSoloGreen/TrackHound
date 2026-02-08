"""Lightweight schema migrations for backward compatibility."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.encryption import encrypt_value, is_encrypted


async def _ensure_bootstrap_user(conn: AsyncConnection) -> int:
    """Return an owner user id, creating a bootstrap owner when necessary."""
    owner_id = await conn.scalar(text("SELECT MIN(id) FROM users"))
    if owner_id is not None:
        return int(owner_id)

    result = await conn.execute(
        text(
            """
            INSERT INTO users (plex_user_id, plex_username, plex_email, plex_token, plex_thumb_url, created_at, last_login)
            VALUES ('bootstrap-owner', 'bootstrap-owner', NULL, :bootstrap_token, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ),
        {"bootstrap_token": encrypt_value("bootstrap-owner-token")},
    )

    inserted_id = result.lastrowid
    if inserted_id is not None:
        return int(inserted_id)

    owner_id = await conn.scalar(
        text("SELECT id FROM users WHERE plex_user_id = 'bootstrap-owner' LIMIT 1")
    )
    return int(owner_id)


async def apply_token_encryption_migration(conn: AsyncConnection) -> None:
    """Encrypt legacy plaintext Plex tokens in-place."""
    result = await conn.execute(text("SELECT id, plex_token FROM users"))
    users = result.fetchall()

    for user_id, plex_token in users:
        if plex_token and not is_encrypted(plex_token):
            await conn.execute(
                text("UPDATE users SET plex_token = :token WHERE id = :id"),
                {"token": encrypt_value(plex_token), "id": user_id},
            )


async def apply_ownership_migrations(conn: AsyncConnection) -> None:
    """Add per-user ownership columns and backfill old rows."""
    inspector = inspect(conn.sync_connection)

    for table_name in ("shows", "media_files", "scan_locations"):
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if "user_id" not in columns:
            await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER"))

    owner_id = await _ensure_bootstrap_user(conn)

    await conn.execute(
        text("UPDATE shows SET user_id = :owner_id WHERE user_id IS NULL"),
        {"owner_id": owner_id},
    )
    await conn.execute(
        text("UPDATE media_files SET user_id = :owner_id WHERE user_id IS NULL"),
        {"owner_id": owner_id},
    )
    await conn.execute(
        text("UPDATE scan_locations SET user_id = :owner_id WHERE user_id IS NULL"),
        {"owner_id": owner_id},
    )

    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scan_locations_user_path ON scan_locations (user_id, path)"
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_shows_user_id ON shows (user_id)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_media_files_user_id ON media_files (user_id)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_scan_locations_user_id ON scan_locations (user_id)")
    )
