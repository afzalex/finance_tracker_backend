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
