import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.api.auth import get_current_user
from app.api.media import router as media_router
from app.api.scan import router as scan_router
from app.models.database import get_db
from app.models.entities import Base, User, Show, ScanLocation


@pytest.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(scan_router, prefix="/api/scan")
    app.include_router(media_router, prefix="/api/media")

    users = {}

    async def override_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async with session_maker() as session:
        user_a = User(plex_user_id="1", plex_username="user-a", plex_token="token-a")
        user_b = User(plex_user_id="2", plex_username="user-b", plex_token="token-b")
        session.add_all([user_a, user_b])
        await session.flush()

        show_b = Show(user_id=user_b.id, title="Other User Show", media_type="tv", is_anime=False)
        session.add(show_b)
        scan_b = ScanLocation(user_id=user_b.id, path="/media/user-b", label="B", media_type="tv", enabled=True)
        session.add(scan_b)
        await session.commit()

        users["a"] = user_a
        users["b"] = user_b
        users["show_b_id"] = show_b.id
        users["scan_b_id"] = scan_b.id

    app.dependency_overrides[get_db] = override_db

    yield app, users

    await engine.dispose()


@pytest.mark.anyio
async def test_user_cannot_view_or_edit_other_users_show(test_app):
    app, users = test_app

    async def override_current_user():
        return users["a"]

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        get_resp = await client.get(f"/api/media/shows/{users['show_b_id']}")
        assert get_resp.status_code == 404

        patch_resp = await client.patch(
            f"/api/media/shows/{users['show_b_id']}",
            json={"media_type": "anime"},
        )
        assert patch_resp.status_code == 404


@pytest.mark.anyio
async def test_user_cannot_access_other_users_scan_locations(test_app):
    app, users = test_app

    async def override_current_user():
        return users["a"]

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_resp = await client.get("/api/scan/locations")
        assert list_resp.status_code == 200
        assert all(loc["id"] != users["scan_b_id"] for loc in list_resp.json())

        get_resp = await client.get(f"/api/scan/locations/{users['scan_b_id']}")
        assert get_resp.status_code == 404

        patch_resp = await client.patch(
            f"/api/scan/locations/{users['scan_b_id']}",
            json={"label": "hijack"},
        )
        assert patch_resp.status_code == 404

        delete_resp = await client.delete(f"/api/scan/locations/{users['scan_b_id']}")
        assert delete_resp.status_code == 404


@pytest.mark.anyio
async def test_create_scan_location_enforces_per_user_path_uniqueness_and_ownership(test_app):
    app, users = test_app

    async def current_user_a():
        return users["a"]

    async def current_user_b():
        return users["b"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = current_user_a

        create_a_resp = await client.post(
            "/api/scan/locations",
            json={
                "path": "/media/shared/library",
                "label": "A Shared",
                "media_type": "tv",
                "enabled": True,
            },
        )
        assert create_a_resp.status_code == 201
        created_a = create_a_resp.json()
        assert created_a["path"] == "/media/shared/library"

        duplicate_a_resp = await client.post(
            "/api/scan/locations",
            json={
                "path": "/media/shared/library",
                "label": "A Duplicate",
                "media_type": "tv",
                "enabled": True,
            },
        )
        assert duplicate_a_resp.status_code == 400

        app.dependency_overrides[get_current_user] = current_user_b

        create_b_resp = await client.post(
            "/api/scan/locations",
            json={
                "path": "/media/shared/library",
                "label": "B Shared",
                "media_type": "movie",
                "enabled": True,
            },
        )
        assert create_b_resp.status_code == 201
        created_b = create_b_resp.json()

        # Ownership check: user B cannot access user A's location, and can access their own.
        get_a_as_b_resp = await client.get(f"/api/scan/locations/{created_a['id']}")
        assert get_a_as_b_resp.status_code == 404

        get_b_as_b_resp = await client.get(f"/api/scan/locations/{created_b['id']}")
        assert get_b_as_b_resp.status_code == 200

        app.dependency_overrides[get_current_user] = current_user_a
        get_b_as_a_resp = await client.get(f"/api/scan/locations/{created_b['id']}")
        assert get_b_as_a_resp.status_code == 404



@pytest.mark.anyio
async def test_user_cannot_start_scan_with_other_users_location_ids(test_app):
    app, users = test_app

    async def override_current_user():
        return users["a"]

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post(
            "/api/scan/start",
            json={"location_ids": [users["scan_b_id"]], "incremental": True},
        )
        assert start_resp.status_code == 404


@pytest.mark.anyio
async def test_user_cannot_start_scan_all_on_only_other_users_locations(test_app):
    app, users = test_app

    async def override_current_user():
        return users["a"]

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post(
            "/api/scan/start",
            json={"incremental": True},
        )
        assert start_resp.status_code == 400
        assert start_resp.json()["detail"] == "No enabled scan locations found"
