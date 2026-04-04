from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.main import create_app
from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
from backend.config import settings
from backend.database import get_db


def test_start_gmail_token_flow_requires_credentials_file(db, tmp_path) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)

    old_creds = settings.gmail_credentials_file
    try:
        settings.gmail_credentials_file = str(tmp_path / "missing_credentials.json")

        r = client.post(
            "/api/v1/admin/mail/gmail/token/start",
            params={"redirect_uri": "http://localhost:8000/api/v1/admin/mail/gmail/token/callback"},
        )
        assert r.status_code == 409
        assert "Missing credentials.json" in r.json()["detail"]
    finally:
        settings.gmail_credentials_file = old_creds


def test_start_gmail_token_flow_returns_auth_url(db, tmp_path) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)

    creds_path = tmp_path / "credentials.json"

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
    try:
        settings.gmail_credentials_file = str(creds_path)

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


def test_finish_gmail_token_flow_unknown_state(db) -> None:
    app = create_app(serve_frontend=False)
    client = TestClient(app)
    r = client.get(
        "/api/v1/admin/mail/gmail/token/callback",
        params={"state": "does-not-exist-12345", "code": "fake-code-12345"},
    )
    assert r.status_code == 400


def test_finish_gmail_token_flow_persists_mail_account(db, tmp_path, monkeypatch) -> None:
    app = create_app(serve_frontend=False)

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    old_creds = settings.gmail_credentials_file
    try:
        creds_path = tmp_path / "credentials.json"
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
        settings.gmail_credentials_file = str(creds_path)

        start = client.post(
            "/api/v1/admin/mail/gmail/token/start",
            params={"redirect_uri": "http://localhost:8000/api/v1/admin/mail/gmail/token/callback"},
        )
        assert start.status_code == 200
        state = start.json()["state"]

        token_blob = {
            "token": "ya29.test",
            "refresh_token": "1//refresh-test",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client-id.apps.googleusercontent.com",
            "client_secret": "test-client-secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        }

        class FakeCreds:
            def to_json(self) -> str:
                return json.dumps(token_blob)

        fake_flow = MagicMock()
        fake_flow.credentials = FakeCreds()
        fake_flow.fetch_token = MagicMock()

        def fake_from_client_secrets_file(*_a, **_k):
            return fake_flow

        monkeypatch.setattr(
            "google_auth_oauthlib.flow.Flow.from_client_secrets_file",
            fake_from_client_secrets_file,
        )

        def fake_build(_service_name, _version, credentials=None):
            class Exec:
                def execute(self_inner):
                    return {"emailAddress": "oauth-test@example.com"}

            class Profile:
                def getProfile(self_inner, userId=None):
                    return Exec()

            class Users:
                def users(self_inner):
                    return Profile()

            return Users()

        monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

        r = client.get(
            "/api/v1/admin/mail/gmail/token/callback",
            params={"state": state, "code": "auth-code-test"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["account_mail_id"] == "oauth-test@example.com"
        assert "mail_account_id" in body

        row = db.scalars(select(MailAccount).where(MailAccount.id == body["mail_account_id"])).one()
        assert row.provider == MAIL_PROVIDER_GMAIL
        assert row.account_mail_id == "oauth-test@example.com"
        assert json.loads(row.token_json or "{}")["token"] == "ya29.test"
        assert row.is_primary is True
    finally:
        settings.gmail_credentials_file = old_creds
        app.dependency_overrides.clear()
