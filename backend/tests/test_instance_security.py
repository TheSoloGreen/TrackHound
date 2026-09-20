"""Production configuration and authorization at the Plex trust boundary."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import auth
from app.config import Settings, _INSECURE_DEFAULT_KEY, _INSECURE_DEFAULT_ENCRYPTION_KEY
from app.models.entities import Base, User
from app.models.engine import create_database_engine


@pytest.mark.parametrize("field,bad_value", [
    ("secret_key", _INSECURE_DEFAULT_KEY),
    ("secret_key", ""),
    ("secret_key", " " * 64),
    ("secret_key", "too-short"),
    ("encryption_key", _INSECURE_DEFAULT_ENCRYPTION_KEY),
    ("encryption_key", ""),
    ("encryption_key", "too-short"),
])
def test_production_rejects_insecure_keys(field, bad_value):
    values = {"secret_key": "s" * 64, "encryption_key": "e" * 44, field: bad_value}
    settings = Settings(environment="production", _env_file=None, **values)
    with pytest.raises(ValueError, match=field.upper()):
        settings.validate_secret_key()


def test_production_accepts_configured_keys():
    Settings(environment="production", secret_key="s" * 64, encryption_key="e" * 44, _env_file=None).validate_secret_key()


def test_allowlist_normalizes_ids_and_defaults_to_no_access():
    assert Settings(allowed_plex_user_ids="", _env_file=None).allowed_plex_user_ids_set == set()
    assert Settings(allowed_plex_user_ids=" 123,00456,123 ", _env_file=None).allowed_plex_user_ids_set == {"123", "456"}


@pytest.mark.parametrize("value", ["*", "username", "-1", "0", "12.3", "123,abc"])
def test_allowlist_rejects_non_account_ids(value):
    with pytest.raises(ValueError, match="numeric Plex account IDs"):
        Settings(allowed_plex_user_ids=value, _env_file=None)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def mock_plex_login(monkeypatch, *, plex_user_id="123"):
    """Return a verified Plex account from the two callback API requests."""
    plex = AsyncMock()
    plex.get.side_effect = [
        httpx.Response(200, json={"authToken": "synthetic-plex-token"}),
        httpx.Response(200, json={"id": plex_user_id, "username": "verified-user"}),
    ]
    context = AsyncMock()
    context.__aenter__.return_value = plex
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda: context)


@pytest.mark.asyncio
async def test_configured_allowlist_remains_authoritative_for_login(monkeypatch, db):
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "456")
    mock_plex_login(monkeypatch, plex_user_id="123")

    with pytest.raises(HTTPException) as exc:
        await auth.complete_plex_login(pin_id=1, db=db)

    assert exc.value.status_code == 403
    assert "123" in exc.value.detail
    assert await db.scalar(select(func.count(User.id))) == 0


@pytest.mark.asyncio
async def test_configured_allowlist_accepts_listed_account(monkeypatch, db):
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "123")
    mock_plex_login(monkeypatch, plex_user_id="123")

    response = await auth.complete_plex_login(pin_id=1, db=db)

    assert response.access_token
    assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_empty_allowlist_bootstraps_first_verified_plex_account(monkeypatch, db):
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")
    mock_plex_login(monkeypatch, plex_user_id="123")

    response = await auth.complete_plex_login(pin_id=1, db=db)

    assert response.access_token
    user = (await db.execute(select(User))).scalar_one()
    assert user.plex_user_id == "123"
    assert user.plex_token.startswith("enc::")


@pytest.mark.asyncio
async def test_empty_allowlist_allows_bootstrapped_account_to_log_back_in(monkeypatch, db):
    db.add(User(plex_user_id="123", plex_username="original", plex_token="test"))
    await db.flush()
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")
    mock_plex_login(monkeypatch, plex_user_id="123")

    response = await auth.complete_plex_login(pin_id=1, db=db)

    assert response.access_token
    assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_empty_allowlist_rejects_second_verified_plex_account(monkeypatch, db):
    db.add(User(plex_user_id="123", plex_username="owner", plex_token="test"))
    await db.flush()
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")
    mock_plex_login(monkeypatch, plex_user_id="456")

    with pytest.raises(HTTPException) as exc:
        await auth.complete_plex_login(pin_id=1, db=db)

    assert exc.value.status_code == 403
    assert "456" in exc.value.detail
    assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_empty_allowlist_preserves_bootstrapped_users_existing_session(monkeypatch, db):
    user = User(plex_user_id="123", plex_username="owner", plex_token="test")
    db.add(user)
    await db.flush()
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=auth.create_access_token(user.id)
    )
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")

    assert await auth.get_current_user(credentials, db) is user


@pytest.mark.asyncio
async def test_concurrent_empty_allowlist_bootstrap_creates_only_one_owner(monkeypatch, tmp_path):
    database = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")

    class PlexClient:
        def __init__(self):
            self.token = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers):
            if url.startswith(auth.PLEX_PINS_URL + "/"):
                pin_id = url.rsplit("/", 1)[-1]
                self.token = f"token-{pin_id}"
                return httpx.Response(200, json={"authToken": self.token})
            plex_user_id = "123" if self.token == "token-1" else "456"
            return httpx.Response(200, json={"id": plex_user_id, "username": plex_user_id})

    monkeypatch.setattr(auth.httpx, "AsyncClient", PlexClient)
    ready = asyncio.Event()

    async def attempt(pin_id):
        async with sessions() as session:
            await ready.wait()
            try:
                await auth.complete_plex_login(pin_id=pin_id, db=session)
                await session.commit()
                return "accepted"
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    tasks = [asyncio.create_task(attempt(pin_id)) for pin_id in (1, 2)]
    ready.set()
    outcomes = await asyncio.gather(*tasks)

    async with sessions() as session:
        owners = (await session.execute(select(User.plex_user_id))).scalars().all()
    await database.dispose()
    assert sorted(outcomes, key=str) == [403, "accepted"]
    assert len(owners) == 1


@pytest.mark.asyncio
async def test_configured_allowlist_revokes_existing_session(monkeypatch, db):
    user = User(plex_user_id="123", plex_username="user", plex_token="test")
    db.add(user)
    await db.flush()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth.create_access_token(user.id))
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "123")
    assert await auth.get_current_user(credentials, db) is user
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "456")
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials, db)
    assert exc.value.status_code == 403
