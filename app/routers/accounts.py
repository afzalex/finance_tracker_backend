"""Accounts router — per-account activity and channel breakdown."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import (
    AccountFromTransactionsMergedRead,
    AccountUpsert,
    AccountUpsertRead,
)
from backend.app.services.account_service import list_accounts_from_transactions, upsert_account
from backend.database import get_db

router = APIRouter()


@router.put(
    "",
    response_model=AccountUpsertRead,
    summary="Upsert account metadata",
)
async def put_account(
    body: AccountUpsert,
    db: Session = Depends(get_db),
) -> AccountUpsertRead:
    """Create or update a row in ``accounts`` for the given ``provider`` + ``account_id``."""
    return upsert_account(db, body)


@router.get(
    "",
    response_model=list[AccountFromTransactionsMergedRead],
    response_model_by_alias=True,
)
async def list_accounts(
    db: Session = Depends(get_db),
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Only include transactions on or after this date (YYYY-MM-DD).",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="Only include transactions on or before this date (YYYY-MM-DD), end of day.",
    ),
    date_from: Optional[date] = Query(
        None,
        description="Same as ``from``.",
    ),
    date_to: Optional[date] = Query(
        None,
        description="Same as ``to``.",
    ),
) -> list[AccountFromTransactionsMergedRead]:
    """Transactions merged by ``account_id`` with amounts, counts, optional ``_conflict``."""
    return list_accounts_from_transactions(
        db,
        date_from=from_date or date_from,
        date_to=to_date or date_to,
    )
