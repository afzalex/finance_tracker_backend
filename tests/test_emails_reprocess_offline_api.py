from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.database import get_db
from tests.conftest import seed_classification, seed_parser


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_reprocess_offline_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post("/api/v1/emails/reprocess?wait=true")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["stats"]["fetched"] == 0


def test_reprocess_offline_processes_all_cached_emails(db) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        provider="HDFC",
        body_extract_regex=(
            r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
        ),
        account_type="SAVINGS",
    )
    db.add(
        FetchedEmail(
            mail_id="m1",
            thread_id="t1",
            subject="Alert",
            sender="hdfcbank@example.com",
            snippet="debited",
            internal_date_ms=1,
            body_text="A/c XX1234 debited INR 10.00",
        )
    )
    db.add(
        FetchedEmail(
            mail_id="m2",
            thread_id="t2",
            subject="Alert",
            sender="hdfcbank@example.com",
            snippet="debited",
            internal_date_ms=2,
            body_text="A/c XX1234 debited INR 20.00",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post("/api/v1/emails/reprocess?wait=true")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["stats"]["fetched"] == 2
