"""Extract plain-text content and metadata from raw Gmail message payloads."""

from __future__ import annotations

import base64
import html
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class EmailContent:
    gmail_message_id: str
    thread_id: str
    subject: str
    sender: str
    snippet: str
    internal_date_ms: int
    body_text: str


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
        gmail_message_id=msg_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        snippet=snippet,
        internal_date_ms=internal_date_ms,
        body_text=body_text,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _collect_parts(payload: Dict[str, Any], wanted_types: List[str]) -> List[str]:
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
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    return " ".join(text.split())
