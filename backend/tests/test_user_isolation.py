import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.api.auth import get_current_user
from app.api.media import router as media_router
from app.api.scan import router as scan_router
from app.core.scan_state import scan_state_manager
from app.models.database import get_db
from app.models.entities import Base, User, Show, ScanLocation, MediaFile


@pytest.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

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

        show_b = Show(
            user_id=user_b.id, title="Other User Show", media_type="tv", is_anime=False
        )
        session.add(show_b)
        scan_b = ScanLocation(
            user_id=user_b.id,
            path="/media/user-b",
            label="B",
            media_type="tv",
            enabled=True,
        )
        session.add(scan_b)
        await session.commit()

        users["a"] = user_a
        users["b"] = user_b
        users["show_b_id"] = show_b.id
        users["scan_b_id"] = scan_b.id
        users["session_maker"] = session_maker

    app.dependency_overrides[get_db] = override_db

    yield app, users

    await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_scan_state():
    await scan_state_manager.reset()
    yield
    await scan_state_manager.reset()


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
async def test_create_scan_location_enforces_per_user_path_uniqueness_and_ownership(
    test_app,
):
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


@pytest.mark.anyio
async def test_scan_status_is_isolated_per_user(test_app):
    app, users = test_app

    async def current_user_a():
        return users["a"]

    async def current_user_b():
        return users["b"]

    await scan_state_manager.start_scan(users["a"].id)
    await scan_state_manager.start_scan(users["b"].id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = current_user_a
        status_a_resp = await client.get("/api/scan/status")
        assert status_a_resp.status_code == 200
        assert status_a_resp.json()["is_running"] is True

        app.dependency_overrides[get_current_user] = current_user_b
        status_b_resp = await client.get("/api/scan/status")
        assert status_b_resp.status_code == 200
        assert status_b_resp.json()["is_running"] is True


@pytest.mark.anyio
async def test_user_cannot_cancel_another_users_scan(test_app):
    app, users = test_app

    async def current_user_a():
        return users["a"]

    async def current_user_b():
        return users["b"]

    await scan_state_manager.start_scan(users["a"].id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = current_user_b
        cancel_b_resp = await client.post("/api/scan/cancel")
        assert cancel_b_resp.status_code == 400

        app.dependency_overrides[get_current_user] = current_user_a
        status_a_resp = await client.get("/api/scan/status")
        assert status_a_resp.status_code == 200
        assert status_a_resp.json()["is_running"] is True

        cancel_a_resp = await client.post("/api/scan/cancel")
        assert cancel_a_resp.status_code == 200


@pytest.mark.anyio
async def test_export_and_reset_files_are_scoped_to_current_user(test_app):
    app, users = test_app

    async with users["session_maker"]() as session:
        show_a = Show(user_id=users["a"].id, title="A Show", media_type="tv", is_anime=False)
        show_b = Show(user_id=users["b"].id, title="B Show", media_type="tv", is_anime=False)
        session.add_all([show_a, show_b])
        await session.flush()

        session.add_all(
            [
                MediaFile(
                    user_id=users["a"].id,
                    show_id=show_a.id,
                    file_path="/media/a/file1.mkv",
                    filename="file1.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing English audio track",
                ),
                MediaFile(
                    user_id=users["b"].id,
                    show_id=show_b.id,
                    file_path="/media/b/file2.mkv",
                    filename="file2.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=False,
                    issue_details=None,
                ),
            ]
        )
        await session.commit()

    async def current_user_a():
        return users["a"]

    app.dependency_overrides[get_current_user] = current_user_a

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        export_resp = await client.get("/api/media/files-export?format=csv")
        assert export_resp.status_code == 200
        assert "file1.mkv" in export_resp.text
        assert "file2.mkv" not in export_resp.text

        reset_resp = await client.delete("/api/media/files")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["deleted_files"] == 1

    async with users["session_maker"]() as session:
        user_a_count = await session.scalar(
            select(func.count(MediaFile.id)).where(MediaFile.user_id == users["a"].id)
        )
        user_b_count = await session.scalar(
            select(func.count(MediaFile.id)).where(MediaFile.user_id == users["b"].id)
        )

    assert user_a_count == 0
    assert user_b_count == 1


@pytest.mark.anyio
async def test_file_issue_category_filters_are_scoped_and_applied(test_app):
    app, users = test_app

    async with users["session_maker"]() as session:
        show_a = Show(user_id=users["a"].id, title="A Show", media_type="tv", is_anime=False)
        show_b = Show(user_id=users["b"].id, title="B Show", media_type="tv", is_anime=False)
        session.add_all([show_a, show_b])
        await session.flush()

        session.add_all(
            [
                MediaFile(
                    user_id=users["a"].id,
                    show_id=show_a.id,
                    file_path="/media/a/missing.mkv",
                    filename="missing.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing English audio track",
                ),
                MediaFile(
                    user_id=users["a"].id,
                    show_id=show_a.id,
                    file_path="/media/a/default.mkv",
                    filename="default.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Default audio track is 'ja', expected English",
                ),
                MediaFile(
                    user_id=users["a"].id,
                    show_id=show_a.id,
                    file_path="/media/a/clean.mkv",
                    filename="clean.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=False,
                    issue_details=None,
                ),
                MediaFile(
                    user_id=users["b"].id,
                    show_id=show_b.id,
                    file_path="/media/b/other.mkv",
                    filename="other.mkv",
                    file_size=100,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing English audio track",
                ),
            ]
        )
        await session.commit()

    async def current_user_a():
        return users["a"]

    app.dependency_overrides[get_current_user] = current_user_a

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_resp = await client.get("/api/media/files?issue_category=missing_required_audio")
        assert missing_resp.status_code == 200
        assert [item["filename"] for item in missing_resp.json()["items"]] == ["missing.mkv"]

        default_resp = await client.get("/api/media/files?issue_category=preferred_not_default")
        assert default_resp.status_code == 200
        assert [item["filename"] for item in default_resp.json()["items"]] == ["default.mkv"]

        export_resp = await client.get("/api/media/files-export?format=csv&issue_category=missing_required_audio")
        assert export_resp.status_code == 200
        assert "missing.mkv" in export_resp.text
        assert "default.mkv" not in export_resp.text
        assert "other.mkv" not in export_resp.text
