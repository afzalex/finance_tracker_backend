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


def test_top_merchants_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/top-merchants")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


def test_top_merchants_debit_only_and_order(db) -> None:
    for mid, merchant, amt, direction in [
        ("a", "Zebra", 100.0, Direction.DEBIT),
        ("b", "Alpha", 500.0, Direction.DEBIT),
        ("c", "Alpha", 100.0, Direction.DEBIT),
        ("d", "Beta", 999.0, Direction.CREDIT),
    ]:
        db.add(
            Transaction(
                mail_id=mid,
                transacted_at=datetime(2026, 4, 1, 12, 0, 0),
                origin=Origin.EMAIL_ALERT,
                amount=str(amt),
                amount_parsed=amt,
                currency="INR",
                direction=direction,
                provider="P",
                merchant=merchant,
            )
        )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/top-merchants?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["merchant"] == "Alpha"
    assert data[0]["total"] == 600.0
    assert data[0]["transaction_count"] == 2
    assert data[1]["merchant"] == "Zebra"


def test_top_merchants_month_filter(db) -> None:
    db.add(
        Transaction(
            mail_id="in",
            transacted_at=datetime(2026, 3, 15, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="10",
            amount_parsed=10.0,
            currency="INR",
            direction=Direction.DEBIT,
            merchant="M",
        )
    )
    db.add(
        Transaction(
            mail_id="out",
            transacted_at=datetime(2026, 4, 15, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="99",
            amount_parsed=99.0,
            currency="INR",
            direction=Direction.DEBIT,
            merchant="M",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/top-merchants?month=2026-03")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["total"] == 10.0
    assert data[0]["transaction_count"] == 1


def test_top_merchants_invalid_month_400(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/top-merchants?month=2026-13")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 400
