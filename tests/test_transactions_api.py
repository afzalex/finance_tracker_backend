from __future__ import annotations

from datetime import datetime

from backend.app.models.transaction import Direction, Origin, Transaction
from backend.app.schemas import TransactionListResponse
from backend.app.services.transaction_service import TransactionListParams, TransactionService


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
