"""Gmail OAuth2 authentication.

Manages the OAuth2 credential lifecycle:
  - Load saved token from ``mail_accounts`` (primary Gmail row).
  - Refresh if expired; persist updated token JSON to the same row.
  - Interactive browser flow writes tokens via ``persist_gmail_oauth_credentials``.
"""

from __future__ import annotations

import json
import logging
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
from backend.config import settings
from backend.database import SessionLocal, commit_with_retry
from backend.ingestion.mail.errors import MailProviderAuthError

logger = logging.getLogger(__name__)

# Read-only Gmail scope — never request write access.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuthError(MailProviderAuthError):
    """Raised when Gmail authentication fails and user action is required."""


def _refresh_error_code(exc: RefreshError) -> str | None:
    """Return Google's OAuth error code from a ``RefreshError``, when present."""
    for detail in exc.args:
        if isinstance(detail, dict):
            code = detail.get("error")
            if isinstance(code, str) and code:
                return code
    return None


def _primary_gmail_account_stmt():
    return (
        select(MailAccount)
        .where(
            MailAccount.provider == MAIL_PROVIDER_GMAIL,
            MailAccount.is_active.is_(True),
        )
        .order_by(MailAccount.is_primary.desc(), MailAccount.id.asc())
        .limit(1)
    )


def persist_gmail_oauth_credentials(db: Session, creds: Credentials) -> MailAccount:
    """Store OAuth credentials after a completed flow; sets profile email when available."""
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email_raw = profile.get("emailAddress")
    if not isinstance(email_raw, str) or not email_raw.strip():
        raise GmailAuthError("Gmail profile did not include an email address.")
    email = email_raw.strip()

    row = db.scalars(
        select(MailAccount).where(
            MailAccount.provider == MAIL_PROVIDER_GMAIL,
            MailAccount.account_mail_id == email,
        )
    ).first()
    if row is None:
        legacy = db.scalars(
            select(MailAccount).where(
                MailAccount.provider == MAIL_PROVIDER_GMAIL,
                MailAccount.account_mail_id.is_(None),
                MailAccount.is_primary.is_(True),
            )
        ).first()
        if legacy is not None:
            row = legacy
            row.account_mail_id = email
        else:
            count = db.scalar(
                select(func.count())
                .select_from(MailAccount)
                .where(MailAccount.provider == MAIL_PROVIDER_GMAIL)
            )
            row = MailAccount(
                provider=MAIL_PROVIDER_GMAIL,
                account_mail_id=email,
                token_json=creds.to_json(),
                is_active=True,
                is_primary=(count == 0),
            )
            db.add(row)

    row.token_json = creds.to_json()
    row.is_active = True
    commit_with_retry(db)
    db.refresh(row)
    logger.info("Gmail OAuth token stored for %s (mail_account id=%s)", email, row.id)
    return row


def get_credentials() -> Credentials:
    """Load or refresh Gmail OAuth2 credentials from the primary ``mail_accounts`` row.

    Raises:
        GmailAuthError: If no valid token exists or refresh fails.
    """
    credentials_file = settings.gmail_credentials_file

    try:
        with SessionLocal() as db:
            row = db.scalars(_primary_gmail_account_stmt()).first()
            token_payload = (row.token_json or "").strip() if row is not None else ""

            creds: Credentials | None = None
            if token_payload:
                try:
                    info = json.loads(token_payload)
                    creds = Credentials.from_authorized_user_info(info, SCOPES)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not load Gmail token from mail_accounts: %s", exc)

            if creds and creds.valid:
                _maybe_backfill_gmail_email(db, row, creds)
                return creds

            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing Gmail access token.")
                try:
                    creds.refresh(Request())
                    if row is not None:
                        row.token_json = creds.to_json()
                        commit_with_retry(db)
                    _maybe_backfill_gmail_email(db, row, creds)
                    return creds
                except RefreshError as exc:
                    error_code = _refresh_error_code(exc)
                    retryable = bool(getattr(exc, "retryable", False))

                    # ``RefreshError`` also represents exhausted temporary failures
                    # (Google 5xx responses, server_error, temporarily_unavailable).
                    # Deleting the refresh token for those failures turns a transient
                    # outage into an unnecessary OAuth reconnect.  Google documents
                    # ``invalid_grant`` as the signal that the grant itself has expired
                    # or been invalidated, so only that response warrants removal.
                    if error_code == "invalid_grant" and not retryable:
                        logger.warning("Gmail refresh token is no longer valid: %s", exc)
                        if row is not None:
                            row.token_json = None
                            commit_with_retry(db)
                        raise GmailAuthError(
                            "Gmail token has expired or been revoked.\n"
                            "Re-authenticate by running:\n"
                            "  python -m backend.cli auth"
                        ) from exc

                    logger.warning(
                        "Gmail token refresh failed; preserving the saved refresh token "
                        "for the next attempt (error=%s, retryable=%s): %s",
                        error_code or "unknown",
                        retryable,
                        exc,
                    )
                    raise GmailAuthError(
                        "Gmail token refresh failed temporarily; the saved connection "
                        "was retained and will be retried automatically."
                    ) from exc

            if not os.path.exists(credentials_file):
                raise GmailAuthError(
                    f"Missing OAuth credentials file: {credentials_file}\n"
                    "Download your Desktop app client secret from Google Cloud Console\n"
                    "(APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop app)\n"
                    "and place it at that path, then run:\n"
                    "  python -m backend.cli auth"
                )

            raise GmailAuthError(
                "No valid Gmail token found.\n"
                "Run the following command to authenticate:\n"
                "  python -m backend.cli auth"
            )
    except GmailAuthError:
        raise
    except OperationalError as exc:
        raise GmailAuthError(
            "Database is missing mail_accounts (run: alembic upgrade head).\n"
            f"Details: {exc}"
        ) from exc


def _maybe_backfill_gmail_email(db: Session, row: MailAccount | None, creds: Credentials) -> None:
    if row is None or row.account_mail_id:
        return
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds)
        prof = service.users().getProfile(userId="me").execute()
        email = prof.get("emailAddress")
        if isinstance(email, str) and email.strip():
            row.account_mail_id = email.strip()
            commit_with_retry(db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not backfill Gmail email for mail_account id=%s: %s", row.id, exc)


def run_oauth_flow() -> None:
    """Run the interactive OAuth2 browser flow and save the resulting token to ``mail_accounts``."""
    credentials_file = settings.gmail_credentials_file

    if not os.path.exists(credentials_file):
        raise GmailAuthError(
            f"Missing OAuth credentials file: {credentials_file}\n"
            "Download your Desktop app client secret from Google Cloud Console\n"
            "(APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop app)\n"
            "and place it at that path."
        )

    logger.info("Starting OAuth2 browser flow using %s", credentials_file)
    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    with SessionLocal() as db:
        persist_gmail_oauth_credentials(db, creds)
    logger.info("Gmail authentication complete; token stored in mail_accounts.")
