import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as application
from app.static import SPAStaticFiles


@pytest.fixture
def client(tmp_path):
    (tmp_path / "index.html").write_text('<html><div id="root">TrackHound</div></html>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("window.trackhound = true;")
    app = FastAPI()
    app.router.routes.extend(application.router.routes)
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True))
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/library", "/library/12", "/files", "/settings"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_direct_client_routes(client, path, method):
    response = client.request(method, path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert ("TrackHound" in response.text) if method == "GET" else not response.content


@pytest.mark.parametrize("path", ["/api/missing", "/api", "/assets/missing.js", "/assets/missing", "/missing.css", "/.env", "/%2E%2E/outside"])
def test_missing_assets_api_and_traversal_do_not_return_spa(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "TrackHound" not in response.text


def test_real_asset_api_and_method_responses_are_preserved(client):
    assert client.get("/api/health").json()["status"] == "healthy"
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and "window.trackhound" in asset.text
    assert client.post("/library/12").status_code == 405
