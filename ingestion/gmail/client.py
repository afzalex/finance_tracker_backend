"""Thin Gmail API client.

Wraps google-api-python-client to list and fetch messages.
All methods are read-only; never calls any write endpoint.
"""

from googleapiclient.discovery import build

from backend.ingestion.gmail.auth import get_credentials


class GmailClient:
    """Minimal read-only Gmail API client.

    TODO: Implement list_messages, get_message, and history-based incremental fetch.
    """

    def __init__(self) -> None:
        creds = get_credentials()
        self._service = build("gmail", "v1", credentials=creds)

    def list_messages(self, query: str = "", max_results: int = 100) -> list[dict]:
        """List message metadata matching a query.

        TODO: Implement with pagination support.
        """
        raise NotImplementedError

    def get_message(self, message_id: str) -> dict:
        """Fetch the full message payload for a given Gmail message ID.

        TODO: Implement with exponential backoff retry.
        """
        raise NotImplementedError

    def get_history(self, start_history_id: str) -> list[dict]:
        """Return messages added since start_history_id (incremental sync).

        TODO: Implement history.list pagination.
        """
        raise NotImplementedError
