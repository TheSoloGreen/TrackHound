"""Real HTTP authentication, credential rotation, bootstrap, and Plex coexistence."""
import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import auth
from app.core.local_auth import bootstrap_local_account, hash_password, verify_password
from app.models.database import get_db
from app.models.engine import create_database_engine
from app.models.entities import Base, User, Show
from test_instance_security import mock_plex_login


@pytest_asyncio.fixture
async def setup(tmp_path, monkeypatch):
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    application = FastAPI()
    application.include_router(auth.router, prefix="/auth")

    @application.get("/protected")
    async def protected(user=Depends(auth.get_current_user)):
        return {"id": user.id}

    async def override_db():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    application.dependency_overrides[get_db] = override_db
    auth._login_windows.clear()
    monkeypatch.setattr(auth.settings, "allowed_plex_user_ids", "")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield sessions, client, tmp_path / 'initial-password'
    await engine.dispose()


async def sign_in(client, password, username="admin"):
    return await client.post('/auth/login', json={"username": username, "password": password})


def bearer(response):
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.mark.asyncio
async def test_first_login_rotation_and_restart(setup):
    sessions, client, path = setup
    await asyncio.gather(bootstrap_local_account(sessions, path), bootstrap_local_account(sessions, path))
    initial = path.read_text().strip()
    async with sessions() as db:
        assert await db.scalar(select(func.count(User.id))) == 1
        user = await db.scalar(select(User))
        assert user.password_hash != initial and verify_password(initial, user.password_hash)
    response = await sign_in(client, initial, 'ADMIN')
    assert response.status_code == 200
    headers = bearer(response)
    me = (await client.get('/auth/me', headers=headers)).json()
    assert me['must_change_password'] and me['has_local_password'] and not me['plex_connected']
    assert 'password_hash' not in me and 'plex_token' not in me
    assert (await client.get('/protected', headers=headers)).status_code == 403
    for new_password in [None, initial]:
        result = await client.put('/auth/account', headers=headers, json={
            'username': 'Owner', 'current_password': initial, 'new_password': new_password})
        assert result.status_code == 400
    result = await client.put('/auth/account', headers=headers, json={
        'username': 'Owner', 'current_password': initial, 'new_password': 'a-new-test-password'})
    assert result.status_code == 200
    assert (await client.get('/auth/me', headers=headers)).status_code == 401
    assert (await client.get('/protected', headers=bearer(result))).status_code == 200
    assert (await sign_in(client, initial)).status_code == 401
    assert (await sign_in(client, 'a-new-test-password', 'OWNER')).status_code == 200
    await bootstrap_local_account(sessions, path)
    assert path.read_text().strip() == initial
    assert (await sign_in(client, 'a-new-test-password', 'owner')).status_code == 200


@pytest.mark.asyncio
async def test_upgrade_adds_local_login_to_existing_owner_without_losing_library(setup, monkeypatch):
    sessions, client, path = setup
    async with sessions() as db:
        user = User(plex_user_id='123', plex_username='plex-owner', plex_token='test')
        db.add(user); await db.flush()
        uid = user.id
        db.add(Show(user_id=uid, title='Existing library'))
        await db.commit()
    old_token = auth.create_access_token(uid)
    await bootstrap_local_account(sessions, path)
    response = await sign_in(client, path.read_text().strip())
    assert (await client.get('/auth/me', headers=bearer(response))).json()['id'] == uid
    assert (await client.get('/auth/me', headers={'Authorization': f'Bearer {old_token}'})).status_code == 200
    # A Plex allowlist governs Plex sessions, not independently verified passwords.
    monkeypatch.setattr(auth.settings, 'allowed_plex_user_ids', '456')
    assert (await client.get('/auth/me', headers=bearer(response))).status_code == 200
    assert (await client.get('/auth/me', headers={'Authorization': f'Bearer {old_token}'})).status_code == 403
    async with sessions() as db:
        assert await db.scalar(select(Show.user_id)) == uid
        assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_lockout_survives_requests_and_expires(setup):
    sessions, client, path = setup
    await bootstrap_local_account(sessions, path)
    for _ in range(5):
        assert (await sign_in(client, 'wrong-password')).status_code == 401
    assert (await sign_in(client, path.read_text().strip())).status_code == 429
    async with sessions() as db:
        user = await db.scalar(select(User))
        user.locked_until = datetime.now() - timedelta(days=1)
        await db.commit()
    assert (await sign_in(client, path.read_text().strip())).status_code == 200


@pytest.mark.asyncio
async def test_multiple_plex_users_keep_independent_libraries(setup):
    sessions, client, path = setup
    async with sessions() as db:
        db.add_all([User(plex_user_id=str(i), plex_username=f'user{i}', plex_token='test') for i in (1, 2)])
        await db.commit()
    await bootstrap_local_account(sessions, path)
    async with sessions() as db:
        assert await db.scalar(select(func.count(User.id))) == 3
        assert not (await db.scalar(select(User).where(User.plex_user_id == '1'))).password_hash


@pytest.mark.asyncio
async def test_link_plex_preserves_local_identity_and_prevents_account_takeover(setup, monkeypatch):
    sessions, client, path = setup
    await bootstrap_local_account(sessions, path)
    async with sessions() as db:
        user = await db.scalar(select(User))
        user.must_change_password = False
        await db.commit()
    headers = bearer(await sign_in(client, path.read_text().strip()))
    mock_plex_login(monkeypatch)
    response = await client.post('/auth/plex/link?pin_id=1', headers=headers)
    assert response.status_code == 200
    me = (await client.get('/auth/me', headers=bearer(response))).json()
    assert me['id'] == 1 and me['plex_connected']
    async with sessions() as db:
        other = User(plex_username='other', username='other', password_hash=hash_password('other-password'))
        db.add(other); await db.commit()
        other_headers = {'Authorization': 'Bearer ' + auth.create_access_token(other.id, 0, 'password')}
    mock_plex_login(monkeypatch)
    result = await client.post('/auth/plex/link?pin_id=1', headers=other_headers)
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_account_update_requires_current_password_and_unique_username(setup):
    sessions, client, path = setup
    await bootstrap_local_account(sessions, path)
    headers = bearer(await sign_in(client, path.read_text().strip()))
    result = await client.put('/auth/account', headers=headers, json={
        'username': 'owner', 'current_password': 'wrong', 'new_password': 'new-test-password'})
    assert result.status_code == 400
    async with sessions() as db:
        db.add(User(plex_username='other', username='taken'))
        await db.commit()
    result = await client.put('/auth/account', headers=headers, json={
        'username': 'TAKEN', 'current_password': path.read_text().strip(), 'new_password': 'new-test-password'})
    assert result.status_code == 409
    assert (await client.put('/auth/account', json={'username': 'owner'})).status_code in (401, 403)


@pytest.mark.asyncio
async def test_unknown_user_attempts_are_bounded(setup):
    _, client, _ = setup
    for _ in range(20):
        assert (await sign_in(client, 'wrong', 'missing')).status_code == 401
    assert (await sign_in(client, 'wrong', 'another-missing')).status_code == 429
