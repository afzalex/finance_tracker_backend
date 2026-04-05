from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_top_with_transactions_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/top-with-transactions")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


def test_top_with_transactions_orders_by_last_transacted_at(db) -> None:
    fe_old = FetchedEmail(
        mail_id="old-msg",
        internal_date_ms=1,
        body_text="b",
        subject="Old",
    )
    fe_new = FetchedEmail(
        mail_id="new-msg",
        internal_date_ms=2,
        body_text="b",
        subject="New",
    )
    db.add(fe_old)
    db.add(fe_new)
    db.flush()
    db.add(FetchedEmailEnrichment(fetched_email_id=fe_old.id, classification="X"))
    db.add(FetchedEmailEnrichment(fetched_email_id=fe_new.id, classification="Y"))
    db.add(
        Transaction(
            mail_id="old-msg",
            transacted_at=datetime(2026, 1, 1, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="1",
            amount_parsed=1.0,
            currency="INR",
            direction=Direction.DEBIT,
        )
    )
    db.add(
        Transaction(
            mail_id="new-msg",
            transacted_at=datetime(2026, 3, 1, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="2",
            amount_parsed=2.0,
            currency="INR",
            direction=Direction.DEBIT,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/top-with-transactions?limit=10")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["mail_id"] == "new-msg"
    assert data[0]["transaction_count"] == 1
    assert data[0]["last_transacted_at"].startswith("2026-03-01")
    assert data[0]["enrichment"]["classification"] == "Y"
    assert data[1]["mail_id"] == "old-msg"


def test_top_with_transactions_skips_without_enrichment(db) -> None:
    fe = FetchedEmail(mail_id="only", internal_date_ms=1, body_text="b")
    db.add(fe)
    db.flush()
    db.add(
        Transaction(
            mail_id="only",
            transacted_at=datetime(2026, 1, 1, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="1",
            amount_parsed=1.0,
            currency="INR",
            direction=Direction.DEBIT,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/top-with-transactions")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == []


def test_top_with_transactions_limit_validation(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/top-with-transactions?limit=11")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 422
