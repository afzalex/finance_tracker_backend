from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_transaction_summary_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/transaction-summary")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    d = r.json()
    assert d["credit_amount"] == 0.0
    assert d["debit_amount"] == 0.0
    assert d["amount"] == 0.0
    assert d["credit_count"] == 0
    assert d["debit_count"] == 0
    assert d["count"] == 0


def test_transaction_summary_aggregates_and_date_filter(db) -> None:
    db.add(
        Transaction(
            mail_id="a",
            transacted_at=datetime(2026, 2, 1, 10, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="100",
            amount_parsed=100.0,
            currency="INR",
            direction=Direction.CREDIT,
            provider="P",
            merchant="M",
        )
    )
    db.add(
        Transaction(
            mail_id="b",
            transacted_at=datetime(2026, 3, 1, 10, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="40",
            amount_parsed=40.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            merchant="M",
        )
    )
    db.add(
        Transaction(
            mail_id="c",
            transacted_at=datetime(2026, 3, 5, 10, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="10",
            amount_parsed=10.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            merchant="M",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r_all = client.get("/api/v1/analytics/transaction-summary")
        r_mar = client.get("/api/v1/analytics/transaction-summary?from=2026-03-01&to=2026-03-31")
    finally:
        app.dependency_overrides.clear()

    assert r_all.status_code == 200
    all_d = r_all.json()
    assert all_d["credit_amount"] == 100.0
    assert all_d["debit_amount"] == 50.0
    assert all_d["amount"] == 50.0
    assert all_d["credit_count"] == 1
    assert all_d["debit_count"] == 2
    assert all_d["count"] == 3

    assert r_mar.status_code == 200
    mar = r_mar.json()
    assert mar["credit_amount"] == 0.0
    assert mar["debit_amount"] == 50.0
    assert mar["credit_count"] == 0
    assert mar["debit_count"] == 2
    assert mar["count"] == 2
