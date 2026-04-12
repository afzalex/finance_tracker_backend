"""Server-side regex extract preview: spans and capturing groups for highlighting."""

from __future__ import annotations

import re
from typing import Any


def _extraction_display_value(m: re.Match[str]) -> str | None:
    """Mirror frontend parser preview: first non-empty capturing group, else full match."""
    if m.lastindex:
        for i in range(1, m.lastindex + 1):
            part = m.group(i)
            if part is not None and len(str(part)) > 0:
                return str(part)
    whole = m.group(0)
    if whole is not None and len(str(whole)) > 0:
        return str(whole)
    return None


def regex_field_preview(pattern: str | None, haystack: str | None) -> dict[str, Any]:
    """Evaluate one optional extract regex against haystack.

    Returns a dict suitable for ``RegexFieldPreviewRead`` / JSON.
    """
    raw = (pattern or "").strip()
    text = haystack or ""
    if not raw:
        return {
            "skipped": True,
            "haystack": text,
            "regex_error": None,
            "matched": None,
            "extracted_value": None,
            "full_match": None,
            "groups": [],
        }
    try:
        rx = re.compile(raw)
    except re.error as exc:
        return {
            "skipped": False,
            "haystack": text,
            "regex_error": str(exc),
            "matched": None,
            "extracted_value": None,
            "full_match": None,
            "groups": [],
        }

    m = rx.search(text)
    if not m:
        return {
            "skipped": False,
            "haystack": text,
            "regex_error": None,
            "matched": False,
            "extracted_value": None,
            "full_match": None,
            "groups": [],
        }

    full_match = {"start": m.start(0), "end": m.end(0)}
    groups: list[dict[str, Any]] = []
    if m.lastindex:
        index_to_name: dict[int, str] = {v: k for k, v in m.re.groupindex.items()}
        for i in range(1, m.lastindex + 1):
            start, end = m.span(i)
            if start < 0 or end < 0 or start >= end:
                continue
            nm = index_to_name.get(i)
            groups.append({"index": i, "name": nm, "start": start, "end": end})

    return {
        "skipped": False,
        "haystack": text,
        "regex_error": None,
        "matched": True,
        "extracted_value": _extraction_display_value(m),
        "full_match": full_match,
        "groups": groups,
    }
