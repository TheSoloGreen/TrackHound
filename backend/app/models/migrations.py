"""Transactional Alembic upgrades and the legacy token-backfill helper."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.encryption import encrypt_value, is_encrypted


async def apply_token_encryption_migration(conn):
    """Retained for callers that explicitly backfill legacy token values."""
    for user_id, token in (await conn.execute(text("SELECT id, plex_token FROM users"))):
        if token and not is_encrypted(token):
            await conn.execute(text("UPDATE users SET plex_token = :token WHERE id = :id"),
                               {"id": user_id, "token": encrypt_value(token)})


def _set_sqlite_foreign_keys(connection, enabled):
    # Use the DBAPI directly: PRAGMA must run outside the DDL transaction.
    cursor = connection.connection.cursor()
    try:
        cursor.execute(f"PRAGMA foreign_keys = {'ON' if enabled else 'OFF'}")
    finally:
        cursor.close()


async def upgrade_database(engine, revision="head"):
    """Commit every pending revision together, or roll all of them back."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))

    def upgrade(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    async with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            await connection.run_sync(_set_sqlite_foreign_keys, False)
            connection = await connection.execution_options(sqlite_transaction_mode="IMMEDIATE")
        try:
            async with connection.begin():
                if not sqlite:
                    await connection.execute(text("SELECT pg_advisory_xact_lock(843219706)"))
                await connection.run_sync(upgrade)
                if sqlite:
                    violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).fetchall()
                    if violations:
                        raise RuntimeError("Database upgrade left foreign-key violations; all changes were rolled back.")
        finally:
            if sqlite:
                await connection.run_sync(_set_sqlite_foreign_keys, True)
