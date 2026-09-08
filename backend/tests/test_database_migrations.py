"""Upgrade actual historical schemas on both supported database engines."""

from datetime import datetime
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from unittest.mock import patch
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.backup import backup_sqlite
from app.core.encryption import decrypt_value
from app.core.scanner import MediaScanner
from app.core.scan_state import scan_state_manager
from app.migrations.schema_v1 import metadata as current_legacy
from app.models.engine import create_database_engine
from app.models.entities import Base, MediaFile, User
from app.models.migrations import upgrade_database, _set_sqlite_foreign_keys
from fixtures.legacy_initial import Base as Initial
from fixtures.legacy_pre_ownership import Base as PreOwnership


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def database(request, tmp_path):
    if request.param == "sqlite":
        engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'source.db'}")
        yield engine
        await engine.dispose()
        return
    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL integration tests")
    url = make_url(postgres_url)
    name = f"trackhound_test_{uuid4().hex}"
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_database_engine(url.set(database=name))
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


async def seed_legacy(engine, version):
    metadata = {"initial": Initial.metadata, "pre_ownership": PreOwnership.metadata,
                "current": current_legacy}[version]
    now = datetime(2026, 1, 1)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

        async def insert(table, **values):
            table = metadata.tables[table]
            return await connection.scalar(table.insert().values(**values).returning(table.c.id))

        user_id = await insert("users", plex_user_id="123", plex_username="owner",
                               plex_token="legacy-plex-token", created_at=now, last_login=now)
        owner = {"user_id": user_id} if version == "current" else {}
        show_id = await insert("shows", title="Test anime", is_anime=True, anime_source="folder",
                               created_at=now, updated_at=now,
                               **({"media_type": "anime"} if version != "initial" else {}), **owner)
        season_id = await insert("seasons", show_id=show_id, season_number=1)
        file_id = await insert("media_files", file_path="/media/anime/episode.mkv", filename="episode.mkv",
                               season_id=season_id, file_size=100, last_modified=now, last_scanned=now,
                               has_issues=False, **({"show_id": show_id} if version != "initial" else {}), **owner)
        await insert("audio_tracks", media_file_id=file_id, track_index=0, language="ja",
                     is_default=True, is_forced=False, title="Original audio")
        await insert("scan_locations", path="/media/anime", label="Anime", enabled=True,
                     file_count=1, created_at=now,
                     **({"is_anime_folder": True} if version == "initial" else {"media_type": "anime"}), **owner)
        await insert("user_preferences", user_id=user_id, key="audio_preferences",
                     value='{"require_japanese_anime":true}')


async def assert_upgraded(engine):
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_ownership_constraints"
        diffs = await connection.run_sync(lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata))
        assert diffs == []
        if connection.dialect.name == "sqlite":
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert not (await connection.execute(text("PRAGMA foreign_key_check"))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["initial", "pre_ownership", "current"])
async def test_historical_upgrade_preserves_rows_and_matches_models(database, version):
    await seed_legacy(database, version)
    await upgrade_database(database)
    await assert_upgraded(database)
    async with database.connect() as connection:
        assert decrypt_value(await connection.scalar(text("SELECT plex_token FROM users WHERE plex_user_id='123'"))) == "legacy-plex-token"
        row = (await connection.execute(text("SELECT user_id, show_id, season_id, file_size FROM media_files"))).one()
        assert tuple(row) == (1, 1, 1, 100)
        assert await connection.scalar(text("SELECT media_type FROM scan_locations")) == "anime"
        assert await connection.scalar(text("SELECT title FROM audio_tracks")) == "Original audio"
        assert await connection.scalar(text("SELECT COUNT(*) FROM user_preferences")) == 1
    await upgrade_database(database)
    await assert_upgraded(database)


@pytest.mark.asyncio
async def test_fresh_upgrade_matches_models(database):
    await upgrade_database(database)
    await assert_upgraded(database)


@pytest.mark.asyncio
async def test_failed_upgrade_rolls_back_schema_rows_and_revision(database):
    await seed_legacy(database, "initial")

    def fail_late(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "CREATE INDEX ix_shows_user_id" in statement:
            raise RuntimeError("injected late migration failure")

    event.listen(database.sync_engine, "before_cursor_execute", fail_late)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await upgrade_database(database)
    finally:
        event.remove(database.sync_engine, "before_cursor_execute", fail_late)
    async with database.connect() as connection:
        columns = await connection.run_sync(lambda sync: {col["name"] for col in inspect(sync).get_columns("shows")})
        assert "user_id" not in columns
        assert not await connection.run_sync(lambda sync: inspect(sync).has_table("alembic_version"))
        assert await connection.scalar(text("SELECT plex_token FROM users")) == "legacy-plex-token"
        assert await connection.scalar(text("SELECT COUNT(*) FROM audio_tracks")) == 1
    await upgrade_database(database)
    await assert_upgraded(database)


@pytest.mark.asyncio
async def test_orphan_cleanup_and_database_cascade(database):
    await seed_legacy(database, "initial")
    async with database.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            await connection.run_sync(_set_sqlite_foreign_keys, False)
        async with connection.begin():
            if not sqlite:
                fk = (await connection.run_sync(lambda sync: inspect(sync).get_foreign_keys("audio_tracks")))[0]
                await connection.execute(text(f'ALTER TABLE audio_tracks DROP CONSTRAINT "{fk["name"]}"'))
            await connection.execute(text("INSERT INTO audio_tracks (media_file_id, track_index, is_default, is_forced) VALUES (999, 1, FALSE, FALSE)"))
            if not sqlite:
                # NOT VALID allows the historical orphan but still models the old FK.
                await connection.execute(text("ALTER TABLE audio_tracks ADD CONSTRAINT audio_tracks_media_file_id_fkey FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE NOT VALID"))
        if sqlite:
            await connection.run_sync(_set_sqlite_foreign_keys, True)
    await upgrade_database(database)
    async with database.begin() as connection:
        assert await connection.scalar(text("SELECT COUNT(*) FROM audio_tracks")) == 1
        await connection.execute(text("DELETE FROM media_files"))
        assert await connection.scalar(text("SELECT COUNT(*) FROM audio_tracks")) == 0


@pytest.mark.asyncio
async def test_shared_paths_and_failed_file_do_not_poison_the_scan(database, tmp_path):
    await upgrade_database(database)
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"probe is mocked")
    async with async_sessionmaker(database, expire_on_commit=False)() as session:
        users = [User(plex_user_id=str(n), plex_username=str(n), plex_token="test") for n in (123, 456)]
        session.add_all(users)
        await session.commit()
        scanner = MediaScanner()
        await scan_state_manager.reset()
        with patch.object(scanner.analyzer, "analyze", return_value={"audio_tracks": []}):
            for user in users:
                assert await scanner.process_file(str(source), str(tmp_path), "movie", user.id, session)
            await session.commit()
            assert len((await session.scalars(select(MediaFile))).all()) == 2
            # Deliberate constraint failure inside one per-file savepoint.
            invalid = tmp_path / "bad.mkv"
            invalid.write_bytes(b"bad")
            assert await scanner.process_file(str(invalid), str(tmp_path), "movie", 9999, session) is None
            valid = tmp_path / "valid.mkv"
            valid.write_bytes(b"valid")
            assert await scanner.process_file(str(valid), str(tmp_path), "movie", users[0].id, session)
            await session.commit()
        stored = (await session.scalars(select(MediaFile).where(MediaFile.file_path == str(source)))).first()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(MediaFile(user_id=stored.user_id, file_path=stored.file_path, filename="duplicate",
                                      file_size=1, last_modified=datetime.now()))
                await session.flush()
        assert len((await session.scalars(select(MediaFile))).all()) == 3
        await scan_state_manager.reset()


@pytest.mark.asyncio
async def test_backup_upgrade_restore(database, tmp_path):
    await seed_legacy(database, "initial")
    sqlite = database.dialect.name == "sqlite"
    backup = tmp_path / ("snapshot.db" if sqlite else "snapshot.dump")
    if sqlite:
        backup_sqlite(Path(database.url.database), backup)
    else:
        container = os.environ.get("TEST_POSTGRES_CONTAINER")
        if not container and (not shutil.which("pg_dump") or not shutil.which("pg_restore")):
            pytest.fail("PostgreSQL recovery tests require pg_dump and pg_restore")
        url = database.url
        environment = {**os.environ, "PGHOST": url.host, "PGPORT": str(url.port or 5432),
                       "PGUSER": url.username, "PGPASSWORD": url.password, "PGDATABASE": url.database}
        prefix = ["docker", "exec", "-i", container] if container else []
        # CI uses the server's own matching pg_dump/pg_restore version.
        dump = subprocess.run([*prefix, "pg_dump", "-U", url.username, "--dbname", url.database, "--format=custom"],
                              env=environment, check=True, capture_output=True, timeout=60)
        backup.write_bytes(dump.stdout)
    await upgrade_database(database)
    await assert_upgraded(database)
    await database.dispose()
    if sqlite:
        with sqlite3.connect(backup) as original, sqlite3.connect(database.url.database) as restored:
            original.backup(restored)
    else:
        # This fixture owns an isolated, disposable database, never the supplied admin DB.
        assert database.url.database.startswith("trackhound_test_")
        async with database.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await database.dispose()
        subprocess.run([*prefix, "pg_restore", "-U", url.username, "--exit-on-error", "--single-transaction", "--no-owner",
                        "--dbname", url.database], input=backup.read_bytes(), env=environment,
                       check=True, capture_output=True, timeout=60)
    async with database.connect() as connection:
        assert not await connection.run_sync(lambda sync: inspect(sync).has_table("alembic_version"))
        assert await connection.scalar(text("SELECT plex_token FROM users")) == "legacy-plex-token"
        assert await connection.scalar(text("SELECT COUNT(*) FROM media_files")) == 1
        assert await connection.scalar(text("SELECT title FROM audio_tracks")) == "Original audio"
    await upgrade_database(database)
    await assert_upgraded(database)


def test_sqlite_backup_includes_wal_and_never_overwrites(tmp_path):
    source, backup = tmp_path / "source.db", tmp_path / "snapshot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('committed in WAL')")
        connection.commit()
        assert source.with_name("source.db-wal").stat().st_size > 0
        backup_sqlite(source, backup)
        before = backup.read_bytes()
        with pytest.raises(FileExistsError):
            backup_sqlite(source, backup)
        assert backup.read_bytes() == before
    with sqlite3.connect(backup) as restored:
        assert restored.execute("SELECT value FROM sample").fetchone()[0] == "committed in WAL"
