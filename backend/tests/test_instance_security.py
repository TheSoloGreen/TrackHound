"""Production configuration and authorization at the Plex trust boundary."""

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


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", ["", "456", "123"])
async def test_plex_login_requires_instance_authorization(monkeypatch, db, allowed):
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", allowed)
    plex = AsyncMock()
    plex.get.side_effect = [
        httpx.Response(200, json={"authToken": "synthetic-plex-token"}),
        httpx.Response(200, json={"id": 123, "username": "approved-user"}),
    ]
    context = AsyncMock()
    context.__aenter__.return_value = plex
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda: context)

    if allowed == "123":
        response = await auth.complete_plex_login(pin_id=1, db=db)
        assert response.access_token
        user = (await db.execute(select(User))).scalar_one()
        assert user.plex_user_id == "123"
        assert user.plex_token.startswith("enc::")
    else:
        with pytest.raises(HTTPException) as exc:
            await auth.complete_plex_login(pin_id=1, db=db)
        assert exc.value.status_code == 403
        assert "123" in exc.value.detail  # Safe first-install account discovery.
        assert await db.scalar(select(func.count(User.id))) == 0


@pytest.mark.asyncio
async def test_removing_allowlist_entry_revokes_existing_session(monkeypatch, db):
    user = User(plex_user_id="123", plex_username="user", plex_token="test")
    db.add(user)
    await db.flush()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth.create_access_token(user.id))
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "123")
    assert await auth.get_current_user(credentials, db) is user
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials, db)
    assert exc.value.status_code == 403
