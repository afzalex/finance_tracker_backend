"""Accounts router — per-account activity and channel breakdown."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.query_params import DateRangeQuery, date_range_query
from backend.app.schemas import (
    AccountFromTransactionsMergedRead,
    AccountUpsert,
    AccountUpsertRead,
    PartyRollupsRead,
)
from backend.app.services.account_service import (
    list_accounts_from_transactions,
    list_party_rollups_from_transactions,
    upsert_account,
)
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
    dates: DateRangeQuery = Depends(date_range_query),
) -> list[AccountFromTransactionsMergedRead]:
    """Transactions merged by ``account_id`` with amounts, counts, optional ``_conflict``."""
    return list_accounts_from_transactions(
        db,
        from_=dates.from_,
        to=dates.to,
    )


@router.get(
    "/parties",
    response_model=PartyRollupsRead,
    summary="Merchant and counterparty rollups from transactions",
)
async def list_parties(
    db: Session = Depends(get_db),
    kind: Optional[Literal["merchant", "counterparty"]] = Query(
        None,
        description=(
            "When omitted, return both ``merchants`` and ``counterparties``. "
            "Use ``merchant`` or ``counterparty`` to return only that list (the other is empty)."
        ),
    ),
    dates: DateRangeQuery = Depends(date_range_query),
) -> PartyRollupsRead:
    """Group non-excluded transactions by merchant and/or counterparty with debit/credit totals."""
    return list_party_rollups_from_transactions(
        db,
        from_=dates.from_,
        to=dates.to,
        kind=kind,
    )
