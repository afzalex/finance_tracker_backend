from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.version import APP_VERSION
from backend.config import settings


def _resolve_setting_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    # tests/... -> backend/
    backend_root = Path(__file__).resolve().parents[1]
    return backend_root / p


def test_app_metadata_basic(db) -> None:
    # Metadata endpoint does not use the DB, but we keep the ``db`` fixture
    # consistent with the rest of the suite environment setup.
    app = create_app(serve_frontend=False)
    client = TestClient(app)

    r = client.get("/api/v1/meta")
    assert r.status_code == 200

    data = r.json()
    assert data["app_version"] == APP_VERSION
    assert data["openapi_url"].endswith("/openapi.json")
    assert data["docs_url"].endswith("/docs")
    assert data["redoc_url"].endswith("/redoc")

    expected_healthy = _resolve_setting_path(settings.gmail_credentials_file).exists()
    assert data["is_healthy"] is expected_healthy

    expected_initialized = (
        _resolve_setting_path(settings.gmail_credentials_file).exists()
        and _resolve_setting_path(settings.gmail_token_file).exists()
    )
    assert data["is_initialized"] is expected_initialized

    # When not initialized we must not claim connectivity works.
    if not expected_initialized:
        assert data["is_mail_connectivity_working"] is False
        assert data["mail_user_email"] is None
        assert data["mail_user_name"] is None


