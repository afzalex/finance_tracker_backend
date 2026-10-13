from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError
from sqlalchemy.orm import sessionmaker

from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
from backend.ingestion.gmail.auth import GmailAuthError, get_credentials


def _expired_credentials(refresh_error: RefreshError) -> MagicMock:
    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "saved-refresh-token"
    creds.expiry = datetime(2020, 1, 1, tzinfo=timezone.utc)
    creds.refresh.side_effect = refresh_error
    return creds


def _seed_mail_account(db) -> tuple[MailAccount, str]:
    token_json = json.dumps(
        {
            "token": "expired-access-token",
            "refresh_token": "saved-refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            "expiry": "2020-01-01T00:00:00Z",
        }
    )
    row = MailAccount(
        provider=MAIL_PROVIDER_GMAIL,
        account_mail_id="owner@example.com",
        token_json=token_json,
        is_active=True,
        is_primary=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token_json


def _patch_credentials(monkeypatch, db, creds: MagicMock) -> None:
    test_session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("backend.ingestion.gmail.auth.SessionLocal", test_session)
    monkeypatch.setattr(
        "backend.ingestion.gmail.auth.Credentials.from_authorized_user_info",
        lambda *_args, **_kwargs: creds,
    )


def test_retryable_refresh_error_preserves_saved_token(db, monkeypatch) -> None:
    row, original_token = _seed_mail_account(db)
    exc = RefreshError(
        "temporarily_unavailable: retry later",
        {"error": "temporarily_unavailable"},
        retryable=True,
    )
    _patch_credentials(monkeypatch, db, _expired_credentials(exc))

    with pytest.raises(GmailAuthError, match="retained"):
        get_credentials()

    db.expire_all()
    assert db.get(MailAccount, row.id).token_json == original_token


def test_unknown_refresh_error_preserves_saved_token(db, monkeypatch) -> None:
    row, original_token = _seed_mail_account(db)
    exc = RefreshError(
        "invalid_client: client configuration rejected",
        {"error": "invalid_client"},
        retryable=False,
    )
    _patch_credentials(monkeypatch, db, _expired_credentials(exc))

    with pytest.raises(GmailAuthError, match="retained"):
        get_credentials()

    db.expire_all()
    assert db.get(MailAccount, row.id).token_json == original_token


def test_invalid_grant_clears_token_and_requires_reconnect(db, monkeypatch) -> None:
    row, _original_token = _seed_mail_account(db)
    exc = RefreshError(
        "invalid_grant: Token has been expired or revoked",
        {"error": "invalid_grant"},
        retryable=False,
    )
    _patch_credentials(monkeypatch, db, _expired_credentials(exc))

    with pytest.raises(GmailAuthError, match="Re-authenticate"):
        get_credentials()

    db.expire_all()
    assert db.get(MailAccount, row.id).token_json is None
