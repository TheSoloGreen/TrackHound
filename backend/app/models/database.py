"""Async database configuration supporting SQLite and PostgreSQL."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.models.engine import create_database_engine

from app.config import get_settings

settings = get_settings()

# Ensure data directory exists for SQLite
if settings.is_sqlite:
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if db_path.startswith("./"):
        db_path = db_path[2:]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_database_engine(settings.database_url, echo=settings.debug)

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
    """Upgrade the schema before serving any application requests."""
    from app.models.migrations import upgrade_database
    await upgrade_database(engine)
