from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.account import Account
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_accounts_from_transactions_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/accounts")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_accounts_merged_by_account_id_sums_and_counts(db) -> None:
    db.add(
        Account(
            provider="HDFC",
            account_id="acc-1",
            account_type="SAVINGS",
            display_name="My HDFC",
        )
    )
    db.commit()

    db.add(
        Transaction(
            mail_id="m1",
            transacted_at=datetime(2026, 3, 29, 9, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="50",
            amount_parsed=50.0,
            currency="INR",
            direction=Direction.CREDIT,
            provider="HDFC",
            account_id="acc-1",
            account_type="SAVINGS",
        )
    )
    db.add(
        Transaction(
            mail_id="m2",
            transacted_at=datetime(2026, 3, 30, 10, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="10",
            amount_parsed=10.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="HDFC",
            account_id="acc-1",
            account_type="SAVINGS",
        )
    )
    db.add(
        Transaction(
            mail_id="m3",
            transacted_at=datetime(2026, 3, 28, 8, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="5",
            amount_parsed=5.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="ICICI",
            account_id="x",
            account_type="CREDIT_CARD",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/accounts")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        by_aid = {x["account_id"]: x for x in body}
        a1 = by_aid["acc-1"]
        assert a1["provider"] == "HDFC"
        assert a1["account_type"] == "SAVINGS"
        assert a1["credit_amount"] == 50.0
        assert a1["debit_amount"] == 10.0
        assert a1["amount"] == 40.0
        assert a1["credit_count"] == 1
        assert a1["debit_count"] == 1
        assert a1["count"] == 2
        assert a1["display_name"] == "My HDFC"
        assert a1["id"] is not None
        assert "_conflict" not in a1 or a1.get("_conflict") is None

        icici = by_aid["x"]
        assert icici["provider"] == "ICICI"
        assert icici["debit_amount"] == 5.0
        assert icici["display_name"] is None
        assert icici["id"] is None
    finally:
        app.dependency_overrides.clear()


def test_accounts_conflict_same_account_id_two_providers(db) -> None:
    # Shared account_id string across banks; HDFC has more rows -> wins provider
    for i, prov in enumerate(["HDFC", "HDFC", "HDFC", "ICICI"]):
        db.add(
            Transaction(
                mail_id=f"c{i}",
                transacted_at=datetime(2026, 1, i + 1, 12, 0, 0),
                origin=Origin.EMAIL_ALERT,
                amount="1",
                amount_parsed=1.0,
                currency="INR",
                direction=Direction.DEBIT,
                provider=prov,
                account_id="SHARED",
                account_type="SAVINGS",
            )
        )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/accounts")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["account_id"] == "SHARED"
        assert row["provider"] == "HDFC"
        assert row["count"] == 4
        assert row["debit_amount"] == 4.0
        conf = row["_conflict"]
        assert len(conf) == 2
        by_p = {c["provider"]: c for c in conf}
        assert by_p["HDFC"]["count"] == 3
        assert by_p["HDFC"]["credit_count"] == 0
        assert by_p["HDFC"]["debit_count"] == 3
        assert by_p["ICICI"]["count"] == 1
        assert by_p["ICICI"]["credit_count"] == 0
        assert by_p["ICICI"]["debit_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_put_account_upsert_insert_and_update(db) -> None:
    client, app = _client_with_db(db)
    try:
        r1 = client.put(
            "/api/v1/accounts",
            json={"provider": "HDFC", "account_id": "A1", "display_name": "First"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["display_name"] == "First"
        pid = d1["id"]

        r2 = client.put(
            "/api/v1/accounts",
            json={"provider": "HDFC", "account_id": "A1", "display_name": "Second"},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["id"] == pid
        assert d2["display_name"] == "Second"
    finally:
        app.dependency_overrides.clear()
