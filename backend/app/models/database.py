"""Async database configuration supporting SQLite and PostgreSQL."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# Ensure data directory exists for SQLite
if settings.is_sqlite:
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if db_path.startswith("./"):
        db_path = db_path[2:]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

sqlite_connect_args = (
    {
        "check_same_thread": False,
        # Wait up to 30s for pending write locks instead of failing fast.
        "timeout": 30,
    }
    if settings.is_sqlite
    else {}
)

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # SQLite-specific settings
    connect_args=sqlite_connect_args,
)

if settings.is_sqlite:
    # Reduce SQLITE_BUSY errors under concurrent read/write load.
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.close()

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    from app.models.entities import Base
    from app.models.migrations import (
        apply_ownership_migrations,
        apply_token_encryption_migration,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await apply_ownership_migrations(conn)
        await apply_token_encryption_migration(conn)
