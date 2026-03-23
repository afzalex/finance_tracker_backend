"""Thin Gmail API client.

Wraps google-api-python-client to list and fetch messages.
All methods are read-only; never calls any write endpoint.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.ingestion.gmail.auth import get_credentials

logger = logging.getLogger(__name__)


class HistoryExpiredError(Exception):
    """Raised when the stored Gmail history ID is too old and can no longer be used."""


class GmailClient:
    """Minimal read-only Gmail API client."""

    def __init__(self) -> None:
        creds = get_credentials()
        self._service = build("gmail", "v1", credentials=creds)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """Return the authenticated user's Gmail profile (includes current historyId)."""
        return self._service.users().getProfile(userId="me").execute()

    def get_label_id(self, label_name: str) -> Optional[str]:
        """Resolve a label name (e.g. "Finance") to its internal Gmail label ID."""
        response = self._service.users().labels().list(userId="me").execute()
        for label in response.get("labels", []):
            if label.get("name", "").lower() == label_name.lower():
                return label.get("id")
        return None

    def list_messages(self, query: str = "", max_results: int = 100) -> list[dict]:
        """Return up to max_results message stubs ({id, threadId}) matching query.

        Pages through the API automatically.
        """
        messages: list[dict] = []
        page_token: Optional[str] = None

        while len(messages) < max_results:
            batch = min(500, max_results - len(messages))
            kwargs: dict = {"userId": "me", "maxResults": batch}
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token

            response = self._service.users().messages().list(**kwargs).execute()
            chunk = response.get("messages", [])
            messages.extend(chunk)

            page_token = response.get("nextPageToken")
            if not page_token or not chunk:
                break

        logger.info("Listed %d messages (query=%r)", len(messages), query)
        return messages[:max_results]

    def iter_message_stubs(
        self, *, query: str = "", max_results: Optional[int] = None
    ) -> Iterator[dict]:
        """Yield message stubs one-by-one (id, threadId) via paginated listing."""
        yielded = 0
        page_token: Optional[str] = None

        while True:
            remaining = max_results - yielded if max_results is not None else 10**18
            batch = min(500, int(remaining))
            if batch <= 0:
                return

            kwargs: dict = {"userId": "me", "maxResults": batch}
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token

            response = self._service.users().messages().list(**kwargs).execute()
            chunk = response.get("messages", []) or []
            for s in chunk:
                msg_id = s.get("id")
                if not msg_id:
                    continue
                yielded += 1
                yield {"id": msg_id, "threadId": s.get("threadId")}
                if max_results is not None and yielded >= max_results:
                    return

            page_token = response.get("nextPageToken")
            if not page_token or not chunk:
                return

    def get_message(self, message_id: str) -> dict:
        """Fetch the full message payload for a given Gmail message ID."""
        return (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def get_history(
        self,
        start_history_id: str,
        label_id: Optional[str] = None,
    ) -> list[dict]:
        """Return message stubs ({id, threadId}) for messages added since start_history_id.

        Raises:
            HistoryExpiredError: If the history ID has expired (Gmail returns 404).
                                 Caller should fall back to a full list_messages fetch.
        """
        kwargs: dict = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded"],
        }
        if label_id:
            kwargs["labelId"] = label_id

        messages: list[dict] = []
        try:
            response = self._service.users().history().list(**kwargs).execute()
            while response:
                for record in response.get("history", []):
                    for added in record.get("messagesAdded", []):
                        msg = added.get("message", {})
                        if msg.get("id"):
                            messages.append({"id": msg["id"], "threadId": msg.get("threadId")})

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
                response = (
                    self._service.users()
                    .history()
                    .list(**kwargs, pageToken=page_token)
                    .execute()
                )
        except HttpError as exc:
            if exc.resp.status == 404:
                raise HistoryExpiredError(
                    f"Gmail history ID {start_history_id!r} has expired; "
                    "a full re-fetch is required."
                ) from exc
            raise

        # Deduplicate by message ID (history can contain duplicates)
        seen: set[str] = set()
        unique: list[dict] = []
        for m in messages:
            if m["id"] not in seen:
                seen.add(m["id"])
                unique.append(m)

        logger.info(
            "History fetch from %s returned %d new messages", start_history_id, len(unique)
        )
        return unique

    def iter_history_message_stubs(
        self, *, start_history_id: str, label_id: Optional[str] = None
    ) -> Iterator[dict]:
        """Yield unique message stubs from Gmail history (deduped by message id)."""
        kwargs: dict = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded"],
        }
        if label_id:
            kwargs["labelId"] = label_id

        seen: set[str] = set()
        try:
            response = self._service.users().history().list(**kwargs).execute()
            while response:
                for record in response.get("history", []) or []:
                    for added in record.get("messagesAdded", []) or []:
                        msg = added.get("message", {}) or {}
                        msg_id = msg.get("id")
                        if msg_id and msg_id not in seen:
                            seen.add(msg_id)
                            yield {"id": msg_id, "threadId": msg.get("threadId")}

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
                response = (
                    self._service.users()
                    .history()
                    .list(**kwargs, pageToken=page_token)
                    .execute()
                )
        except HttpError as exc:
            if exc.resp.status == 404:
                raise HistoryExpiredError(
                    f"Gmail history ID {start_history_id!r} has expired; "
                    "a full re-fetch is required."
                ) from exc
            raise
