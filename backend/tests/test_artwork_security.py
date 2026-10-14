from types import SimpleNamespace as NS
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.api import media
from app.api.auth import create_access_token
from app.core.artwork import artwork_reference, public_avatar_url
from app.core.encryption import encrypt_value
from app.core.plex_connector import PlexConnector, PlexArtworkError, MAX_ARTWORK_BYTES
from app.models.database import get_db
from app.models.entities import Show, User, InstanceSettings
from test_scanner_run_scan import library


@pytest.mark.parametrize("value,expected", [
    ("https://plex.invalid/library/metadata/12/thumb/1?X-Plex-Token=synthetic", "/library/metadata/12/thumb/1"),
    ("/library/metadata/12/thumb", "/library/metadata/12/thumb"),
    ("/library/metadata/12/thumb/1?x-plex-token=synthetic", "/library/metadata/12/thumb/1"),
    ("https://other.invalid/arbitrary", None), ("//other.invalid/arbitrary", None),
    ("/library/metadata/12/thumb/../../admin", None), ("javascript:alert(1)", None),
])
def test_only_token_free_thumbnail_paths_are_retained(value, expected):
    assert artwork_reference(value) == expected


def test_avatar_urls_drop_credentials_and_fragments():
    assert public_avatar_url("https://avatar.invalid/a?size=80&X%2DPlex%2DToken=synthetic#secret") == "https://avatar.invalid/a?size=80"
    assert public_avatar_url("https://user:synthetic@avatar.invalid/a") is None


def artwork_client(*chunks, status=200, content_type="image/png"):
    response = Mock(status_code=status, headers={"Content-Type": content_type})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = iter(chunks)
    server = NS(url=Mock(return_value="https://selected-plex.invalid/library/metadata/12/thumb/1"),
                _headers=Mock(return_value={"X-Plex-Token": "synthetic-server-token"}),
                _session=NS(get=Mock(return_value=response)))
    client = PlexConnector("synthetic-account-token")
    client._server = server
    return client, server


def test_artwork_uses_selected_server_and_header_auth_without_redirects():
    client, server = artwork_client(b"image")
    assert client.fetch_artwork("https://untrusted.invalid/library/metadata/12/thumb/1?X-Plex-Token=bad") == (b"image", "image/png")
    server.url.assert_called_once_with("/library/metadata/12/thumb/1", includeToken=False)
    server._session.get.assert_called_once_with(
        "https://selected-plex.invalid/library/metadata/12/thumb/1",
        headers={"X-Plex-Token": "synthetic-server-token"}, timeout=10, stream=True, allow_redirects=False)


@pytest.mark.parametrize("status,content_type,chunks", [
    (302, "image/png", [b"image"]), (200, "image/svg+xml", [b"svg"]),
    (200, "text/html", [b"html"]), (200, "image/png", []),
    (200, "image/png", [b"x" * (MAX_ARTWORK_BYTES + 1)]),
])
def test_artwork_rejects_redirects_active_content_empty_and_oversized_responses(status, content_type, chunks):
    client, _ = artwork_client(*chunks, status=status, content_type=content_type)
    with pytest.raises(PlexArtworkError, match="^Artwork is unavailable.$"):
        client.fetch_artwork("/library/metadata/12/thumb/1")


def test_artwork_errors_do_not_expose_upstream_credentials():
    client, server = artwork_client(b"image")
    server._session.get.side_effect = RuntimeError("https://plex.invalid/?X-Plex-Token=synthetic")
    with pytest.raises(PlexArtworkError) as error:
        client.fetch_artwork("/library/metadata/12/thumb/1")
    assert "synthetic" not in str(error.value)


@pytest.mark.asyncio
async def test_catalog_and_artwork_endpoint_enforce_auth_and_ownership(library, monkeypatch):
    async with library.sessions() as db:
        owner = await db.get(User, library.user.id)
        owner.plex_token = encrypt_value("synthetic-account-token")
        other = User(plex_username="other", username="other", password_hash="synthetic-hash")
        db.add(other)
        db.add(InstanceSettings(id=1, owner_user_id=owner.id, auth_required=True))
        show = Show(user_id=owner.id, title="Movie", thumb_url="https://plex.invalid/library/metadata/12/thumb/1?X-Plex-Token=synthetic")
        db.add(show)
        await db.commit()
        show_id, other_id = show.id, other.id
        listed = await media.list_shows(owner, db, page=1, page_size=25)
        assert listed.items[0].thumb_url == f"/api/media/shows/{show_id}/artwork"
        assert "synthetic" not in listed.model_dump_json()
        detail = await media.get_show(show_id, owner, db)
        assert detail.thumb_url == listed.items[0].thumb_url

    async def database():
        async with library.sessions() as db:
            yield db
    fetch = Mock(return_value=(b"image", "image/png"))
    monkeypatch.setattr(PlexConnector, "fetch_artwork", fetch)
    application = FastAPI()
    application.include_router(media.router, prefix="/api/media")
    application.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            path = f"/api/media/shows/{show_id}/artwork"
            assert (await client.get(path)).status_code == 401
            other_token = create_access_token(other_id, method="password")
            assert (await client.get(path, headers={"Authorization": f"Bearer {other_token}"})).status_code == 404
            owner_token = create_access_token(library.user.id)
            response = await client.get(path, headers={"Authorization": f"Bearer {owner_token}"})
            assert response.status_code == 200 and response.content == b"image"
            assert response.headers["Cache-Control"] == "private, no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            fetch.assert_called_once_with("/library/metadata/12/thumb/1")
    finally:
        application.dependency_overrides.clear()
