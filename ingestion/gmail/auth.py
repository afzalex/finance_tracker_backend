"""Gmail OAuth2 authentication.

Manages the OAuth2 credential lifecycle:
  - Load saved token from GMAIL_TOKEN_FILE.
  - Refresh if expired.
  - Run the local web-server flow on first run to obtain a new token.
  - Save the refreshed/new token back to GMAIL_TOKEN_FILE.
"""

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from backend.config import settings

# Read-only Gmail scope — never request write access.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_credentials() -> Credentials:
    """Load or refresh Gmail OAuth2 credentials.

    Returns a valid ``Credentials`` object ready for use with the Gmail API.

    TODO: Implement token load, refresh, and first-run OAuth2 flow.
    """
    raise NotImplementedError
