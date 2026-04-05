"""Analytics router — charts and breakdowns for the dashboard."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.schemas import (
    CategoryBreakdown,
    CashflowPoint,
    Direction,
    MerchantSummary,
    TransactionSummaryRead,
)
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.transaction_service import TransactionListParams, TransactionService
from backend.database import get_db

router = APIRouter()


@router.get(
    "/transaction-summary",
    response_model=TransactionSummaryRead,
    summary="Credit/debit totals and counts",
)
async def transaction_summary(
    db: Session = Depends(get_db),
    account_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    direction: Optional[Direction] = Query(None),
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive.",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="End date (YYYY-MM-DD), inclusive end of day.",
    ),
    date_from: Optional[date] = Query(None, description="Same as ``from``."),
    date_to: Optional[date] = Query(None, description="Same as ``to``."),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
) -> TransactionSummaryRead:
    """Aggregate sums and counts over transactions using the same filters as ``GET /transactions``."""
    eff_from = from_date or date_from
    eff_to = to_date or date_to
    ca, da, cc, dc = TransactionService(db).transaction_summary(
        TransactionListParams(
            page=1,
            page_size=1,
            account_id=account_id,
            provider=provider,
            category=category,
            direction=direction,
            date_from=eff_from,
            date_to=eff_to,
            search=search,
        )
    )
    return TransactionSummaryRead(
        credit_amount=ca,
        debit_amount=da,
        amount=ca - da,
        credit_count=cc,
        debit_count=dc,
        count=cc + dc,
    )


@router.get("/cashflow", response_model=list[CashflowPoint])
async def cashflow(
    db: Session = Depends(get_db),
    months: int = Query(12, ge=1, le=60, description="Number of months to return"),
) -> list[CashflowPoint]:
    """Monthly income vs expense for the past N months.

    TODO: Implement in AnalyticsService.
    """
    raise NotImplementedError


@router.get("/category-breakdown", response_model=list[CategoryBreakdown])
async def category_breakdown(
    db: Session = Depends(get_db),
    month: Optional[str] = Query(None, description="Filter to a specific month (YYYY-MM)"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> list[CategoryBreakdown]:
    """Spending by category.

    TODO: Implement in AnalyticsService.
    """
    raise NotImplementedError


@router.get("/top-merchants", response_model=list[MerchantSummary])
async def top_merchants(
    db: Session = Depends(get_db),
    month: Optional[str] = Query(
        None,
        pattern=r"^\d{4}-\d{2}$",
        description="Restrict to calendar month (YYYY-MM). Combined with ``from``/``to`` when both set.",
    ),
    limit: int = Query(10, ge=1, le=100),
    account_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive.",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="End date (YYYY-MM-DD), inclusive end of day.",
    ),
    date_from: Optional[date] = Query(None, description="Same as ``from``."),
    date_to: Optional[date] = Query(None, description="Same as ``to``."),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
) -> list[MerchantSummary]:
    """Top merchants by total DEBIT ``amount_parsed``. Same filters as ``GET /transactions`` except ``direction`` is ignored."""
    eff_from = from_date or date_from
    eff_to = to_date or date_to
    params = TransactionListParams(
        page=1,
        page_size=1,
        account_id=account_id,
        provider=provider,
        category=category,
        direction=None,
        date_from=eff_from,
        date_to=eff_to,
        search=search,
    )
    try:
        return AnalyticsService(db).top_merchants(params, limit=limit, month=month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/recurring")
async def recurring_transactions(db: Session = Depends(get_db)) -> dict:
    """Detect recurring transactions by pattern.

    TODO: Implement in AnalyticsService.
    """
    raise NotImplementedError


@router.get("/anomalies")
async def anomaly_highlights(db: Session = Depends(get_db)) -> dict:
    """Highlight transactions significantly above usual category amounts.

    TODO: Implement in AnalyticsService.
    """
    raise NotImplementedError
