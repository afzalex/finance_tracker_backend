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


def test_reprocess_email_by_mail_id_404(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post("/api/v1/emails/missing/reprocess")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404


def test_reprocess_email_by_mail_id_processes_cached_row(db) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        provider="HDFC",
        body_extract_regex=(
            r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
            r".*?ref\s+(?P<txn_id>\w+)"
        ),
        account_type="SAVINGS",
    )

    # Pre-existing cached email row in fetched_emails (offline mode source).
    db.add(
        FetchedEmail(
            mail_id="mid-1",
            thread_id="t1",
            subject="Alert",
            sender="hdfcbank@example.com",
            snippet="debited",
            internal_date_ms=0,
            body_text="A/c XX1234 debited INR 500.00 ref TXN777",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.post("/api/v1/emails/mid-1/reprocess")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    payload = r.json()
    assert payload["mail_id"] == "mid-1"
    assert payload["stats"]["fetched"] == 1
