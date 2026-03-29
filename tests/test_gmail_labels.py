"""Tests for multi-label Gmail config and pipeline query/history helpers."""

from __future__ import annotations

from typing import Iterator, Optional

import pytest

from backend.config import Settings
from backend.ingestion.pipeline import _gmail_label_query, _iter_history_for_labels


def test_gmail_labels_comma_separated() -> None:
    s = Settings(gmail_label="Finance, Bank ")
    assert s.gmail_labels == ["Finance", "Bank"]


def test_gmail_labels_single_trimmed() -> None:
    s = Settings(gmail_label="  Finance  ")
    assert s.gmail_labels == ["Finance"]


def test_gmail_labels_empty_falls_back_to_finance() -> None:
    s = Settings(gmail_label="  ,  ")
    assert s.gmail_labels == ["Finance"]


def test_gmail_label_query_single() -> None:
    assert _gmail_label_query(["Finance"]) == "label:Finance"


def test_gmail_label_query_multiple_or() -> None:
    q = _gmail_label_query(["Finance", "Receipts"])
    assert q == "(label:Finance OR label:Receipts)"


def test_gmail_label_query_space_in_name_quoted() -> None:
    assert _gmail_label_query(["My Alerts"]) == 'label:"My Alerts"'


def test_gmail_label_query_escapes_quote_in_name() -> None:
    assert _gmail_label_query(['Say "Hi"']) == 'label:"Say \\"Hi\\""'


class _FakeGmailClient:
    """Minimal stand-in for history merge tests."""

    def get_label_id(self, label_name: str) -> Optional[str]:
        return {"A": "idA", "B": "idB"}.get(label_name)

    def iter_history_message_stubs(
        self, *, start_history_id: str, label_id: Optional[str] = None
    ) -> Iterator[dict]:
        _ = start_history_id
        if label_id == "idA":
            yield {"id": "m1", "threadId": "t1"}
            yield {"id": "m2", "threadId": "t2"}
        elif label_id == "idB":
            yield {"id": "m2", "threadId": "t2"}
            yield {"id": "m3", "threadId": "t3"}


def test_iter_history_for_labels_dedupes_message_ids() -> None:
    client = _FakeGmailClient()
    stubs = list(_iter_history_for_labels(client, "100", ["A", "B"]))
    assert [s["id"] for s in stubs] == ["m1", "m2", "m3"]


def test_iter_history_for_labels_skips_unknown_label(caplog: pytest.LogCaptureFixture) -> None:
    client = _FakeGmailClient()
    stubs = list(_iter_history_for_labels(client, "100", ["A", "Missing", "B"]))
    assert [s["id"] for s in stubs] == ["m1", "m2", "m3"]
    assert any("Missing" in r.message for r in caplog.records)
