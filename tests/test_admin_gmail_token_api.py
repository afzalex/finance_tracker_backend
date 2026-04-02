from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.config import settings


def test_start_gmail_token_flow_requires_credentials_file(db, tmp_path) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)

    old_creds = settings.gmail_credentials_file
    old_token = settings.gmail_token_file
    try:
        settings.gmail_credentials_file = str(tmp_path / "missing_credentials.json")
        settings.gmail_token_file = str(tmp_path / "token.json")

        r = client.post(
            "/api/v1/admin/mail/gmail/token/start",
            params={"redirect_uri": "http://localhost:8000/api/v1/admin/mail/gmail/token/callback"},
        )
        assert r.status_code == 409
        assert "Missing credentials.json" in r.json()["detail"]
    finally:
        settings.gmail_credentials_file = old_creds
        settings.gmail_token_file = old_token


def test_start_gmail_token_flow_returns_auth_url(db, tmp_path) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)

    creds_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"

    creds_path.write_text(
        """
{
  "installed": {
    "client_id": "test-client-id.apps.googleusercontent.com",
    "project_id": "test-project",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "test-client-secret",
    "redirect_uris": ["http://localhost:8000/api/v1/admin/mail/gmail/token/callback"]
  }
}
""".strip(),
        encoding="utf-8",
    )

    old_creds = settings.gmail_credentials_file
    old_token = settings.gmail_token_file
    try:
        settings.gmail_credentials_file = str(creds_path)
        settings.gmail_token_file = str(token_path)
        assert not os.path.exists(settings.gmail_token_file)

        r = client.post(
            "/api/v1/admin/mail/gmail/token/start",
            params={"redirect_uri": "http://localhost:8000/api/v1/admin/mail/gmail/token/callback"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "auth_url" in data and data["auth_url"].startswith("https://")
        assert "state" in data and isinstance(data["state"], str) and len(data["state"]) > 10
    finally:
        settings.gmail_credentials_file = old_creds
        settings.gmail_token_file = old_token


def test_finish_gmail_token_flow_unknown_state(db) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)
    r = client.get(
        "/api/v1/admin/mail/gmail/token/callback",
        params={"state": "does-not-exist-12345", "code": "fake-code-12345"},
    )
    assert r.status_code == 400

