"""Transactions router — paginated, filterable transaction list."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from backend.app.schemas import (
    AccountType,
    Direction,
    Status,
    SubType,
    TransactionDistinctCatalog,
    TransactionListResponse,
    TransactionRead,
    TransactionType,
    TransactionUpdate,
)
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
            "is_self_transfer": bool(txn.is_self_transfer),
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


@router.patch(
    "/{transaction_id}",
    response_model=TransactionRead,
    summary="Update editable transaction fields",
)
async def patch_transaction(
    transaction_id: int = Path(..., ge=1, description="Primary key ``transactions.id``."),
    body: TransactionUpdate = ...,
    db: Session = Depends(get_db),
) -> TransactionRead:
    """Currently only ``is_self_transfer`` may be changed."""
    txn = TransactionService(db).update_transaction_is_self_transfer(
        transaction_id,
        is_self_transfer=body.is_self_transfer,
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.commit()
    db.refresh(txn)
    return _read(txn)


@router.get(
    "/distinct",
    response_model=TransactionDistinctCatalog,
    summary="Distinct providers, merchants, and counterparties",
)
async def distinct_transaction_catalog(
    db: Session = Depends(get_db),
    include_merchants_in_counterparties: bool = Query(
        False,
        description=(
            "When true, ``counterparties`` is the union of distinct ``counterparty_name`` "
            "and distinct ``merchant`` values (``merchants`` is unchanged)."
        ),
    ),
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive; alias of ``date_from``.",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="End date (YYYY-MM-DD), inclusive; alias of ``date_to``.",
    ),
    date_from: Optional[date] = Query(
        None,
        description="Same as query param ``from`` (start date, YYYY-MM-DD).",
    ),
    date_to: Optional[date] = Query(
        None,
        description="Same as query param ``to`` (end date, YYYY-MM-DD).",
    ),
) -> TransactionDistinctCatalog:
    """Distinct ``provider``, ``merchant``, and ``counterparty_name`` values.

    Optional ``from`` / ``to`` (or ``date_from`` / ``date_to``) limit to ``transacted_at`` in that
    range, matching ``GET /transactions``.

    Rows with no counterparty name (or no merchant where the UI uses counterparty) may contribute
    ``__NO_COUNTERPARTY__`` in ``counterparties`` (see ``unnamed_counterparty_key``).
    ``has_self_transfer_transactions`` is true if any row has ``is_self_transfer`` set.
    """
    eff_from = from_date or date_from
    eff_to = to_date or date_to
    providers, merchants, counterparties, has_self = TransactionService(db).distinct_catalog(
        include_merchants_in_counterparties=include_merchants_in_counterparties,
        date_from=eff_from,
        date_to=eff_to,
    )
    return TransactionDistinctCatalog(
        providers=providers,
        merchants=merchants,
        counterparties=counterparties,
        has_self_transfer_transactions=has_self,
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
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive; alias of ``date_from``.",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="End date (YYYY-MM-DD), inclusive; alias of ``date_to``.",
    ),
    date_from: Optional[date] = Query(
        None,
        description="Same as query param ``from`` (start date, YYYY-MM-DD).",
    ),
    date_to: Optional[date] = Query(
        None,
        description="Same as query param ``to`` (end date, YYYY-MM-DD).",
    ),
    counterparty: Optional[str] = Query(
        None,
        description=(
            "Exact trimmed value matching ``counterparty_name`` or ``merchant``, or "
            "``__NO_COUNTERPARTY__`` for rows where both ``counterparty_name`` and ``merchant`` null."
        ),
    ),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
    sort_by: str = Query(
        "transacted_at",
        pattern=(
            "^(transacted_at|amount|merchant|provider|account_id|"
            "transaction_type|counterparty)$"
        ),
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> TransactionListResponse:
    eff_from = from_date or date_from
    eff_to = to_date or date_to
    service = TransactionService(db)
    items, total = service.list_transactions(
        TransactionListParams(
            page=page,
            page_size=page_size,
            account_id=account_id,
            provider=provider,
            category=category,
            direction=direction,
            date_from=eff_from,
            date_to=eff_to,
            counterparty=counterparty,
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
