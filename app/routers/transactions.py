"""Transactions router — paginated, filterable transaction list."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import AccountType, Direction, Status, SubType, TransactionListResponse, TransactionRead, TransactionType
from backend.app.services.transaction_service import TransactionListParams, TransactionService
from backend.database import get_db

router = APIRouter()

def _upper(v: str | None) -> str | None:
    return v.upper() if isinstance(v, str) else None

def _enum_or_none(enum_cls, v: str | None):
    if v is None:
        return None
    try:
        return enum_cls(_upper(v))
    except Exception:
        return None

def _status(v: str | None):
    if v is None:
        return None
    try:
        return Status(_upper(v))
    except Exception:
        return Status.UNKNOWN

def _read(txn) -> TransactionRead:
    # Legacy DB tolerance: invalid values are coerced per legacy README.
    # - transaction_type/sub_type/account_type: invalid -> None
    # - status: invalid -> UNKNOWN
    return TransactionRead.model_validate(
        {
            "id": txn.id,
            "mail_id": txn.mail_id,
            "provider": _upper(txn.provider),
            "account_id": txn.account_id,
            "account_last4": txn.account_last4,
            "card_last4": txn.card_last4,
            "card_network": txn.card_network,
            "card_brand": txn.card_brand,
            "amount": txn.amount,
            "amount_parsed": txn.amount_parsed,
            "currency": txn.currency,
            "direction": txn.direction,
            "merchant": txn.merchant,
            "counterparty_name": txn.counterparty_name,
            "counterparty_vpa": txn.counterparty_vpa,
            "counterparty_account": txn.counterparty_account,
            "counterparty_number": txn.counterparty_number,
            "counterparty_id": txn.counterparty_id,
            "category": txn.category,
            "transaction_type": _enum_or_none(TransactionType, txn.transaction_type),
            "sub_type": _enum_or_none(SubType, txn.sub_type),
            "account_type": _enum_or_none(AccountType, txn.account_type),
            "status": _status(txn.status),
            "txn_id": txn.txn_id,
            "fee_amount": txn.fee_amount,
            "balance": txn.balance,
            "reward_points": txn.reward_points,
            "parser_id": txn.parser_id,
            "classification_id": txn.classification_id,
            "transacted_at": txn.transacted_at,
            "created_at": txn.created_at,
        }
    )


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    account_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    direction: Optional[Direction] = Query(None),
    date_from: Optional[date] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[date] = Query(None, description="ISO date YYYY-MM-DD"),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
    sort_by: str = Query("transacted_at", pattern="^(transacted_at|amount|merchant)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> TransactionListResponse:
    service = TransactionService(db)
    items, total = service.list_transactions(
        TransactionListParams(
            page=page,
            page_size=page_size,
            account_id=account_id,
            provider=provider,
            category=category,
            direction=direction,
            date_from=date_from,
            date_to=date_to,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )

    return TransactionListResponse(
        items=[_read(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )
