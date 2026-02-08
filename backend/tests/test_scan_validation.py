from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.scan import _invalid_scan_input, _validate_scan_media_type
from app.main import app
from app.models.database import get_db


class DummySession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("DB should not be called for invalid payload validation")


async def override_get_db():
    yield DummySession()


async def override_get_current_user():
    return SimpleNamespace(plex_token="test-token")


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user


client = TestClient(app)


def test_create_scan_location_invalid_media_type_returns_400():
    response = client.post(
        "/api/scan/locations",
        json={
            "path": "/media/library",
            "label": "Library",
            "media_type": "documentary",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "Invalid request input."
    assert any("media_type" in error for error in body["errors"])


def test_create_scan_location_out_of_scope_path_returns_400():
    response = client.post(
        "/api/scan/locations",
        json={
            "path": "/tmp/library",
            "label": "Library",
            "media_type": "tv",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "Invalid request input."
    assert any("Path must be under /media." in error for error in body["errors"])


def test_defensive_media_type_validator_rejects_invalid_value():
    try:
        _validate_scan_media_type("invalid")
        assert False, "Expected HTTPException for invalid media type"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["detail"] == "Invalid request input."
        assert any(
            "media_type must be one of: tv, movie, anime." in error
            for error in exc.detail["errors"]
        )


def test_invalid_scan_input_helper_returns_consistent_payload():
    exc = _invalid_scan_input("Path must be under /media.")

    assert exc.status_code == 400
    assert exc.detail == {
        "detail": "Invalid request input.",
        "errors": ["Path must be under /media."],
    }
