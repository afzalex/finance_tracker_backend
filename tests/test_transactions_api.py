from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.app.schemas import TransactionListResponse
from backend.app.services.transaction_service import TransactionListParams, TransactionService
from backend.database import get_db


def test_transaction_service_list_transactions_basic(db) -> None:
    db.add(
        Transaction(
            mail_id="m1",
            transacted_at=datetime(2026, 3, 30, 10, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="123.45",
            amount_parsed=123.45,
            currency="INR",
            direction=Direction.DEBIT,
            provider="HDFC",
            account_id="acc-1",
            merchant="Amazon",
            category="Shopping",
        )
    )
    db.add(
        Transaction(
            mail_id="m2",
            transacted_at=datetime(2026, 3, 29, 9, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="50.00",
            amount_parsed=50.0,
            currency="INR",
            direction=Direction.CREDIT,
            provider="HDFC",
            account_id="acc-1",
            merchant="Refund",
            category="Shopping",
        )
    )
    db.commit()

    service = TransactionService(db)
    items, total = service.list_transactions(
        TransactionListParams(page=1, page_size=50, provider="HDFC", sort_by="transacted_at", sort_order="desc")
    )

    assert total == 2
    assert [t.mail_id for t in items] == ["m1", "m2"]

    # Ensure schema serialization works (from_attributes=True).
    payload = TransactionListResponse(items=items, total=total, page=1, page_size=50).model_dump()
    assert payload["total"] == 2
    assert payload["items"][0]["mail_id"] == "m1"


def test_transactions_api_filters_from_to_query_aliases(db) -> None:
    db.add(
        Transaction(
            mail_id="early",
            transacted_at=datetime(2026, 1, 5, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="1",
            amount_parsed=1.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            account_id="a",
        )
    )
    db.add(
        Transaction(
            mail_id="mid",
            transacted_at=datetime(2026, 2, 10, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="2",
            amount_parsed=2.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            account_id="a",
        )
    )
    db.commit()

    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.get("/api/v1/transactions?from=2026-02-01&to=2026-02-28")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["mail_id"] == "mid"


def test_patch_transaction_is_self_transfer(db) -> None:
    t = Transaction(
        mail_id="patch-me",
        transacted_at=datetime(2026, 1, 1, 12, 0, 0),
        origin=Origin.EMAIL_ALERT,
        amount="10",
        amount_parsed=10.0,
        currency="INR",
        direction=Direction.DEBIT,
        provider="P",
        is_self_transfer=False,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    tid = t.id

    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.patch(
            f"/api/v1/transactions/{tid}",
            json={"is_self_transfer": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == tid
    assert body["is_self_transfer"] is True
    assert body["mail_id"] == "patch-me"

    db.expire_all()
    row = db.get(Transaction, tid)
    assert row is not None
    assert row.is_self_transfer is True


def test_patch_transaction_not_found(db) -> None:
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.patch(
            "/api/v1/transactions/999999",
            json={"is_self_transfer": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404
    assert r.json()["detail"] == "Transaction not found"
