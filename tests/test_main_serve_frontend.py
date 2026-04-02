from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_root_serves_index_when_frontend_enabled() -> None:
    app = create_app(serve_frontend=True)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Finance Tracker" in r.text


def test_root_404_when_frontend_disabled() -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)
    assert client.get("/").status_code == 404


def test_health_unaffected_by_frontend_flag() -> None:
    for flag in (True, False):
        app = create_app(serve_frontend=flag)
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
