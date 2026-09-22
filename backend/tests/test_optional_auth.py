"""Default public access, explicit opt-in, ownership, and build identity."""
import asyncio
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, func

from app.api import auth
from app.api.settings import reset_settings
from app.core.instance import bootstrap_instance
from app.core.local_auth import hash_password
from app.main import app, reject_cross_origin_writes
from app.models.entities import InstanceSettings, User, Show
from app.version import VERSION, BUILD_REVISION
from test_local_auth import setup, sign_in, bearer


@pytest.mark.asyncio
async def test_fresh_instance_opens_without_credentials(setup):
    sessions, client, _ = setup
    await asyncio.gather(bootstrap_instance(sessions), bootstrap_instance(sessions))
    assert (await client.get('/auth/config')).json() == {'mode': 'none'}
    assert (await client.get('/protected')).status_code == 200
    # Stale browser tokens do not prevent access to the shared library.
    assert (await client.get('/protected', headers={'Authorization': 'Bearer expired'})).status_code == 200
    me = (await client.get('/auth/me')).json()
    assert me['username'] == 'admin' and not me['has_local_password']
    async with sessions() as db:
        assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_enable_disable_restart_and_reenable_preserve_identity(setup):
    sessions, client, _ = setup
    await bootstrap_instance(sessions)
    original = (await client.get('/protected')).json()
    for body in [{'mode': 'login'}, {'mode': 'login', 'username': 'owner'}]:
        assert (await client.put('/auth/config', json=body)).status_code == 400
    assert (await client.get('/auth/config')).json()['mode'] == 'none'
    response = await client.put('/auth/config', json={'mode': 'login', 'username': 'OWNER', 'password': 'owner-test-password'})
    assert response.status_code == 200
    assert (await client.get('/protected')).status_code == 401
    assert (await client.put('/auth/config', json={'mode': 'none'})).status_code == 401
    headers = bearer(await sign_in(client, 'owner-test-password', 'owner'))
    assert (await client.get('/protected', headers=headers)).json() == original
    await bootstrap_instance(sessions)
    assert (await client.get('/auth/config')).json()['mode'] == 'login'
    # Resetting user preferences must not disable authentication.
    async with sessions() as db:
        await reset_settings(await db.get(User, original['id']), db)
        await db.commit()
    assert (await client.get('/auth/config')).json()['mode'] == 'login'
    assert (await client.put('/auth/config', headers=headers, json={'mode': 'none'})).status_code == 200
    assert (await client.get('/protected')).json() == original
    await bootstrap_instance(sessions)
    assert (await client.get('/auth/config')).json()['mode'] == 'none'
    assert (await client.put('/auth/config', json={'mode': 'login', 'username': 'owner', 'password': 'different-password'})).status_code == 200
    assert (await client.get('/protected', headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_upgrade_preserves_single_user_library_and_ignores_initial_change_flag_in_none_mode(setup):
    sessions, client, _ = setup
    async with sessions() as db:
        owner = User(plex_user_id='123', plex_username='existing', plex_token='synthetic',
                     username='renamed-owner', password_hash=hash_password('test-password'), must_change_password=True)
        db.add(owner); await db.flush()
        uid = owner.id
        db.add(Show(user_id=uid, title='Existing library'))
        await db.commit()
    await bootstrap_instance(sessions)
    assert (await client.get('/protected')).json()['id'] == uid
    async with sessions() as db:
        assert await db.scalar(select(Show.user_id)) == uid
        assert await db.scalar(select(func.count(User.id))) == 1


@pytest.mark.asyncio
async def test_only_owner_can_change_required_mode(setup):
    sessions, client, _ = setup
    await bootstrap_instance(sessions)
    await client.put('/auth/config', json={'mode': 'login', 'username': 'owner', 'password': 'owner-test-password'})
    async with sessions() as db:
        other = User(plex_username='other', username='other', password_hash=hash_password('other-test-password'))
        db.add(other); await db.commit()
    headers = bearer(await sign_in(client, 'other-test-password', 'other'))
    assert (await client.put('/auth/config', headers=headers, json={'mode': 'none'})).status_code == 403
    assert (await client.get('/auth/config')).json()['mode'] == 'login'


@pytest.mark.asyncio
async def test_concurrent_enable_has_one_winner(setup):
    sessions, client, _ = setup
    await bootstrap_instance(sessions)
    responses = await asyncio.gather(*[client.put('/auth/config', json={
        'mode': 'login', 'username': f'owner{i}', 'password': f'test-password-{i}'}) for i in range(2)])
    assert [r.status_code for r in responses].count(200) == 1
    assert all(r.status_code in (200, 401, 409) for r in responses)
    assert (await client.get('/protected')).status_code == 401


@pytest.mark.asyncio
async def test_duplicate_username_does_not_partially_enable_auth(setup):
    sessions, client, _ = setup
    await bootstrap_instance(sessions)
    async with sessions() as db:
        db.add(User(plex_username='other', username='taken'))
        await db.commit()
    response = await client.put('/auth/config', json={'mode': 'login', 'username': 'taken', 'password': 'owner-test-password'})
    assert response.status_code == 409
    assert (await client.get('/auth/config')).json()['mode'] == 'none'
    assert (await client.get('/protected')).status_code == 200


@pytest.mark.asyncio
async def test_build_info_is_uncached_and_agrees_with_health():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        info = await client.get('/api/info')
        assert info.json() == {'version': VERSION, 'revision': BUILD_REVISION}
        assert info.headers['cache-control'] == 'no-store'
        assert (await client.get('/api/health')).json()['version'] == VERSION


@pytest.mark.asyncio
async def test_cross_origin_form_writes_are_rejected():
    application = FastAPI()
    application.middleware('http')(reject_cross_origin_writes)
    @application.post('/write')
    async def write():
        return {'ok': True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://test') as client:
        assert (await client.post('/write', headers={'Origin': 'https://unrelated.example'})).status_code == 403
        assert (await client.post('/write', headers={'Origin': 'null'})).status_code == 403
        assert (await client.post('/write', headers={'Origin': 'http://test'})).status_code == 200
