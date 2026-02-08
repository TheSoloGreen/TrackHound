import pytest
from fastapi import BackgroundTasks
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.scan import start_scan
from app.core.encryption import decrypt_value, encrypt_value, is_encrypted
from app.core.scan_state import scan_state_manager
from app.models.entities import Base, ScanLocation, User
from app.models.migrations import apply_token_encryption_migration
from app.models.schemas import ScanStartRequest


@pytest.mark.anyio
async def test_token_backfill_encrypts_legacy_plaintext_rows():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                """
                INSERT INTO users (plex_user_id, plex_username, plex_email, plex_token, plex_thumb_url, created_at, last_login)
                VALUES
                    ('legacy', 'legacy-user', NULL, 'plaintext-token', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('already', 'encrypted-user', NULL, :encrypted_token, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"encrypted_token": encrypt_value("already-secret")},
        )

        await apply_token_encryption_migration(conn)

        rows = (await conn.execute(text("SELECT plex_user_id, plex_token FROM users"))).fetchall()

    row_map = {row[0]: row[1] for row in rows}
    assert is_encrypted(row_map["legacy"])
    assert decrypt_value(row_map["legacy"]) == "plaintext-token"
    assert decrypt_value(row_map["already"]) == "already-secret"

    await engine.dispose()


@pytest.mark.anyio
async def test_scan_runtime_receives_decrypted_token_when_db_value_is_encrypted():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        user = User(
            plex_user_id="1",
            plex_username="scanner-user",
            plex_token=encrypt_value("runtime-plaintext-token"),
        )
        session.add(user)
        await session.flush()

        session.add(
            ScanLocation(
                user_id=user.id,
                path="/media/library",
                label="Library",
                media_type="tv",
                enabled=True,
            )
        )
        await session.commit()

    await scan_state_manager.reset()
    async with session_maker() as session:
        user = (await session.execute(select(User).where(User.plex_user_id == "1"))).scalar_one()
        bg = BackgroundTasks()

        response = await start_scan(
            request=ScanStartRequest(incremental=True),
            background_tasks=bg,
            current_user=user,
            db=session,
        )

        assert response.is_running is True
        assert len(bg.tasks) == 1
        assert bg.tasks[0].kwargs["user_plex_token"] == "runtime-plaintext-token"

    await scan_state_manager.reset()
    await engine.dispose()
