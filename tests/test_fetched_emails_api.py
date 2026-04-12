from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.database import get_db
from tests.conftest import seed_classification, seed_parser


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_get_fetched_email_with_enrichment_returns_nested_payload(db) -> None:
    fe = FetchedEmail(
        mail_id="gmail-msg-1",
        thread_id="t1",
        subject="Alert",
        sender="bank@example.com",
        snippet="debited",
        internal_date_ms=1_700_000_000_000,
        body_text="Full body text here.",
    )
    db.add(fe)
    db.flush()
    cl = seed_classification(
        db, name="HDFC debit rule", message_type="TRANSACTION_ALERT", sender_match_regex=r"bank"
    )
    pr = seed_parser(db, name="HDFC body parser", sender_match_regex=r"bank")
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe.id,
            classification_id=cl.id,
            classification="TRANSACTION_ALERT",
            classification_reason="Test rule",
            parser_id=pr.id,
            processing_time_ms=42,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get(f"/api/v1/emails/{fe.mail_id}")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["id"] == fe.id
    assert data["mail_id"] == "gmail-msg-1"
    assert data["body_text"] == "Full body text here."
    assert data["enrichment"] is not None
    assert data["enrichment"]["fetched_email_id"] == fe.id
    assert data["enrichment"]["classification"] == "TRANSACTION_ALERT"
    assert data["enrichment"]["classification_reason"] == "Test rule"
    assert data["enrichment"]["parser_id"] == pr.id
    assert data["enrichment"]["classification_name"] == "HDFC debit rule"
    assert data["enrichment"]["parser_name"] == "HDFC body parser"
    assert data["enrichment"]["processing_time_ms"] == 42


def test_get_fetched_email_without_enrichment(db) -> None:
    fe = FetchedEmail(
        mail_id="gmail-msg-2",
        thread_id=None,
        subject=None,
        sender=None,
        snippet=None,
        internal_date_ms=0,
        body_text="x",
    )
    db.add(fe)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get(f"/api/v1/emails/{fe.mail_id}")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["mail_id"] == "gmail-msg-2"
    assert data["enrichment"] is None


def test_get_fetched_email_orphan_ids_have_null_names(db) -> None:
    """If enrichment references deleted/missing classification or parser rows, names are null."""
    fe = FetchedEmail(
        mail_id="gmail-orphan",
        thread_id="t1",
        subject="S",
        sender="s@x.com",
        snippet="",
        internal_date_ms=0,
        body_text="b",
    )
    db.add(fe)
    db.flush()
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe.id,
            classification_id=999_999,
            classification="TRANSACTION_ALERT",
            classification_reason="x",
            parser_id=888_888,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get(f"/api/v1/emails/{fe.mail_id}")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    enr = r.json()["enrichment"]
    assert enr["classification_name"] is None
    assert enr["parser_name"] is None


def test_get_fetched_email_404(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unknown-mail-id-xyz")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404


def test_get_email_detail_uses_mail_id_not_surrogate_pk(db) -> None:
    """Path segment is ``mail_id``; ``/api/v1/emails/1`` is not ``WHERE id = 1``."""
    fe = FetchedEmail(
        mail_id="provider-msg-abc",
        internal_date_ms=0,
        body_text="x",
    )
    db.add(fe)
    db.flush()
    assert fe.id == 1
    client, app = _client_with_db(db)
    try:
        r_by_numeric_path = client.get("/api/v1/emails/1")
        r_by_mail_id = client.get("/api/v1/emails/provider-msg-abc")
    finally:
        app.dependency_overrides.clear()
    assert r_by_numeric_path.status_code == 404
    assert r_by_mail_id.status_code == 200
    assert r_by_mail_id.json()["mail_id"] == "provider-msg-abc"


def test_match_preview_single_mail_id(db) -> None:
    fe = FetchedEmail(
        mail_id="m-prev-1",
        subject="Payment received",
        sender="alerts@bank.example",
        snippet="ok",
        internal_date_ms=1_700_000_000_000,
        body_text="Your payment of INR 100 was received.",
    )
    db.add(fe)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/match-preview",
            json={
                "mail_id": "m-prev-1",
                "subject_match_regex": r"Payment",
                "sender_match_regex": r"bank\.example",
                "body_match_regex": r"INR\s+100",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["mail_id"] == "m-prev-1"
    assert data["matched"] is True
    assert data["scanned"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["mail_id"] == "m-prev-1"
    assert "payment" in data["items"][0]["body_text"].lower()
    assert data["tested_mail"] is not None
    assert data["tested_mail"]["mail_id"] == "m-prev-1"
    assert "payment" in data["tested_mail"]["body_text"].lower()


def test_match_preview_single_mail_not_matched(db) -> None:
    fe = FetchedEmail(
        mail_id="m-prev-2",
        subject="Other",
        sender="x@y.com",
        snippet="",
        internal_date_ms=1_700_000_000_000,
        body_text="body",
    )
    db.add(fe)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/match-preview",
            json={
                "mail_id": "m-prev-2",
                "subject_match_regex": r"Payment",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["matched"] is False


def test_match_preview_top_n(db) -> None:
    db.add(
        FetchedEmail(
            mail_id="n-a",
            subject="Alpha pay",
            sender="a@x.com",
            snippet="",
            internal_date_ms=1_800_000_000_000,
            body_text="b",
        )
    )
    db.add(
        FetchedEmail(
            mail_id="n-b",
            subject="Beta pay",
            sender="b@x.com",
            snippet="",
            internal_date_ms=1_799_000_000_000,
            body_text="b",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/match-preview",
            json={
                "subject_match_regex": r"pay",
                "limit": 2,
                "lookback_days": 3650,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["matched"] is None
    assert data["mail_id"] is None
    assert len(data["items"]) == 2
    assert {row["mail_id"] for row in data["items"]} == {"n-a", "n-b"}
    for row in data["items"]:
        assert row["body_text"] == "b"


def test_extract_regex_preview_spans_and_named_group(db) -> None:
    fe = FetchedEmail(
        mail_id="rx-prev-1",
        subject="Payment INR 500 done",
        sender="a@b.com",
        snippet="snip tail",
        internal_date_ms=1_700_000_000_000,
        body_text="Payment INR 999 credited",
    )
    db.add(fe)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/extract-regex-preview",
            json={
                "mail_id": "rx-prev-1",
                "subject_extract_regex": r"(?P<code>INR\s+\d+)",
                "body_extract_regex": r"(?P<amt>INR\s+\d+)",
                "snippet_extract_regex": r"tail",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["mail_id"] == "rx-prev-1"
    sub = data["subject"]
    assert sub["skipped"] is False
    assert sub["matched"] is True
    assert sub["regex_error"] is None
    assert sub["full_match"] == {"start": 8, "end": 15}
    names = {g["name"]: (g["start"], g["end"]) for g in sub["groups"]}
    assert names["code"] == (8, 15)
    assert sub["extracted_value"] == "INR 500"

    body = data["body"]
    assert body["matched"] is True
    assert body["haystack"].startswith("Payment")
    amt_spans = [g for g in body["groups"] if g["name"] == "amt"]
    assert len(amt_spans) == 1
    assert amt_spans[0]["start"] == body["full_match"]["start"]
    assert amt_spans[0]["end"] == body["full_match"]["end"]


def test_extract_regex_preview_invalid_regex(db) -> None:
    fe = FetchedEmail(
        mail_id="rx-prev-bad",
        subject="x",
        sender="y",
        snippet="z",
        internal_date_ms=1_700_000_000_000,
        body_text="b",
    )
    db.add(fe)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/extract-regex-preview",
            json={
                "mail_id": "rx-prev-bad",
                "subject_extract_regex": r"(unclosed",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    sub = r.json()["subject"]
    assert sub["regex_error"] is not None
    assert sub["matched"] is None


def test_extract_regex_preview_unknown_mail(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/emails/extract-regex-preview",
            json={"mail_id": "missing-id", "subject_extract_regex": r"."},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404
