from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.constants import DISTINCT_UNNAMED_COUNTERPARTY
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.app.services.transaction_service import TransactionService
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def _txn(**kwargs):
    base = dict(
        mail_id="m",
        transacted_at=datetime(2026, 1, 1, 12, 0, 0),
        origin=Origin.EMAIL_ALERT,
        amount="1",
        amount_parsed=1.0,
        currency="INR",
        direction=Direction.DEBIT,
    )
    base.update(kwargs)
    return Transaction(**base)


def test_distinct_catalog_service(db) -> None:
    db.add(
        _txn(
            mail_id="a",
            provider="HDFC",
            merchant="Amazon",
            counterparty_name="Alice",
        )
    )
    db.add(
        _txn(
            mail_id="b",
            provider="HDFC",
            merchant="Swiggy",
            counterparty_name="Bob",
        )
    )
    db.add(
        _txn(
            mail_id="c",
            provider="ICICI",
            merchant="Amazon",
            counterparty_name=None,
        )
    )
    db.commit()

    p, m, c = TransactionService(db).distinct_catalog(
        include_merchants_in_counterparties=False
    )
    assert p == ["HDFC", "ICICI"]
    assert m == ["Amazon", "Swiggy"]
    assert DISTINCT_UNNAMED_COUNTERPARTY in c
    assert c == ["Alice", "Bob", DISTINCT_UNNAMED_COUNTERPARTY]

    p2, m2, c2 = TransactionService(db).distinct_catalog(include_merchants_in_counterparties=True)
    assert p2 == p and m2 == m
    assert set(c2) == {"Alice", "Bob", "Amazon", "Swiggy", DISTINCT_UNNAMED_COUNTERPARTY}
    assert len(c2) == 5


def test_distinct_catalog_unnamed_merchant(db) -> None:
    db.add(
        _txn(
            mail_id="u1",
            provider="P",
            merchant=None,
            counterparty_name="X",
        )
    )
    db.add(_txn(mail_id="u2", provider="P", merchant="  ", counterparty_name="Y"))
    db.commit()

    p, m, c = TransactionService(db).distinct_catalog()
    assert p == ["P"]
    assert m == []
    assert "X" in c and "Y" in c


def test_distinct_catalog_api_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/transactions/distinct")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == {
        "providers": [],
        "merchants": [],
        "counterparties": [],
        "unnamed_counterparty_key": DISTINCT_UNNAMED_COUNTERPARTY,
    }


def test_distinct_catalog_date_range(db) -> None:
    db.add(
        _txn(
            mail_id="jan",
            provider="OnlyJan",
            merchant="JanMerchant",
            counterparty_name="JanCp",
            transacted_at=datetime(2026, 1, 15, 12, 0, 0),
        )
    )
    db.add(
        _txn(
            mail_id="feb",
            provider="OnlyFeb",
            merchant="FebMerchant",
            counterparty_name="FebCp",
            transacted_at=datetime(2026, 2, 15, 12, 0, 0),
        )
    )
    db.commit()

    p, m, c = TransactionService(db).distinct_catalog(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    )
    assert p == ["OnlyJan"]
    assert m == ["JanMerchant"]
    assert c == ["JanCp"]

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/transactions/distinct?from=2026-01-01&to=2026-01-31")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["providers"] == ["OnlyJan"]
    assert data["merchants"] == ["JanMerchant"]
    assert data["counterparties"] == ["JanCp"]


def test_distinct_catalog_api_with_query(db) -> None:
    db.add(_txn(mail_id="x", provider="P1", merchant="M1", counterparty_name="C1"))
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/transactions/distinct?include_merchants_in_counterparties=true")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["providers"] == ["P1"]
    assert data["merchants"] == ["M1"]
    assert set(data["counterparties"]) == {"C1", "M1"}
