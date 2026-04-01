"""Gmail OAuth2 authentication.

Manages the OAuth2 credential lifecycle:
  - Load saved token from GMAIL_TOKEN_FILE.
  - Refresh if expired.
  - Run the local web-server flow on first run to obtain a new token.
  - Save the refreshed/new token back to GMAIL_TOKEN_FILE.
"""

import logging
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from backend.config import settings
from backend.ingestion.mail.errors import MailProviderAuthError

logger = logging.getLogger(__name__)

# Read-only Gmail scope — never request write access.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuthError(MailProviderAuthError):
    """Raised when Gmail authentication fails and user action is required."""


def get_credentials() -> Credentials:
    """Load or refresh Gmail OAuth2 credentials.

    Returns a valid ``Credentials`` object ready for use with the Gmail API.

    Raises:
        GmailAuthError: If no valid token exists or refresh fails — the caller
            should surface the message to the user and direct them to run
            ``finance-tracker auth``.
    """
    token_file = settings.gmail_token_file
    credentials_file = settings.gmail_credentials_file

    creds: Credentials | None = None

    # 1. Try loading a saved token.
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load token file %s: %s", token_file, exc)

    # 2. Valid token — return immediately.
    if creds and creds.valid:
        return creds

    # 3. Expired but refreshable.
    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing Gmail access token.")
        try:
            creds.refresh(Request())
            _save_credentials(creds, token_file)
            return creds
        except RefreshError as exc:
            logger.warning("Gmail refresh token revoked: %s", exc)
            _delete_file(token_file)
            raise GmailAuthError(
                "Gmail token has expired or been revoked.\n"
                "Re-authenticate by running:\n"
                "  python -m backend.cli auth"
            ) from exc

    # 4. No usable token — direct user to run auth.
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


def run_oauth_flow() -> None:
    """Run the interactive OAuth2 browser flow and save the resulting token.

    Opens a local browser window for the user to grant Gmail read access.
    The resulting token is written to ``settings.gmail_token_file``.

    Raises:
        GmailAuthError: If the credentials file is missing.
    """
    credentials_file = settings.gmail_credentials_file
    token_file = settings.gmail_token_file

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
    _save_credentials(creds, token_file)
    logger.info("Gmail authentication complete. Token saved to %s", token_file)


def _save_credentials(creds: Credentials, token_file: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    logger.debug("Saved Gmail token to %s", token_file)


def _delete_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
