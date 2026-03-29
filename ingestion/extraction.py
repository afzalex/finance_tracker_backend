"""Extract plain-text content and metadata from raw Gmail message payloads."""

from __future__ import annotations

import base64
import html
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class EmailContent:
    """Normalised representation of a single mail message (Gmail API today).

    Attributes:
        mail_id:          Provider-stable message id (e.g. Gmail ``id``).
        thread_id:        Provider thread / conversation id.
        subject:          Decoded ``Subject`` header.
        sender:           ``From`` header value (may include display name).
        snippet:          Short provider preview of the body.
        internal_date_ms: Message receipt timestamp in milliseconds since epoch.
        body_text:        Plain-text body (HTML converted to text when no plain part exists).
        fetched_email_id: Internal ``fetched_emails.id`` after persist; set by the pipeline.
    """

    mail_id: str
    thread_id: str
    subject: str
    sender: str
    snippet: str
    internal_date_ms: int
    body_text: str
    fetched_email_id: Optional[int] = field(default=None, repr=False)


def extract_email_content(message: Dict[str, Any]) -> EmailContent:
    """Build an EmailContent from a full Gmail API message dict (format='full')."""
    msg_id = message.get("id", "")
    thread_id = message.get("threadId", "")
    snippet = message.get("snippet", "") or ""
    internal_date_ms = int(message.get("internalDate", 0) or 0)

    headers = {
        h.get("name", ""): h.get("value", "")
        for h in (message.get("payload", {}) or {}).get("headers", [])
    }
    subject = headers.get("Subject", "")
    sender = headers.get("From", "")

    payload = message.get("payload", {}) or {}
    plain_parts = _collect_parts(payload, ["text/plain"])
    html_parts = _collect_parts(payload, ["text/html"]) if not plain_parts else []

    if plain_parts:
        body_text = "\n\n".join(p.strip() for p in plain_parts if p.strip())
    elif html_parts:
        body_text = _html_to_text("\n\n".join(html_parts))
    else:
        body_text = ""

    logger.debug(
        "Extracted email id=%s sender=%s subject=%s body_len=%d",
        msg_id, sender, subject, len(body_text),
    )
    return EmailContent(
        mail_id=msg_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        snippet=snippet,
        internal_date_ms=internal_date_ms,
        body_text=body_text,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _collect_parts(payload: Dict[str, Any], wanted_types: List[str]) -> List[str]:
    """Recursively walk a MIME payload tree and collect body data of the given MIME types."""
    texts: List[str] = []
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")
    if mime_type in wanted_types and data:
        texts.append(_decode_body(data))
    for part in payload.get("parts", []) or []:
        texts.extend(_collect_parts(part, wanted_types))
    return texts


def _decode_body(data: Optional[str]) -> str:
    """Decode a URL-safe base64-encoded Gmail body part to a UTF-8 string."""
    if not data:
        return ""
    try:
        missing = len(data) % 4
        if missing:
            data += "=" * (4 - missing)
        raw = base64.urlsafe_b64decode(data.encode("utf-8"))
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _html_to_text(html_content: str) -> str:
    """Strip HTML tags and return collapsed plain text via BeautifulSoup."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    return " ".join(text.split())
