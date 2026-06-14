"""Analytics router — charts and breakdowns for the dashboard."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.query_params import DateRangeQuery, date_range_query
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


def _twelve_month_window_start(anchor: date) -> date:
    """First day of the calendar month 11 months before ``anchor``'s month (12 months inclusive)."""
    y, m = anchor.year, anchor.month
    m -= 11
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1)


def _effective_cashflow_range(
    from_: Optional[date],
    to: Optional[date],
) -> tuple[date, date]:
    """Resolve inclusive ``from``/``to`` for cashflow; default last 12 months through today when both absent."""
    if from_ is None and to is None:
        eff_to = date.today()
        eff_from = _twelve_month_window_start(eff_to)
        return eff_from, eff_to
    eff_to = to if to is not None else date.today()
    eff_from = from_ if from_ is not None else _twelve_month_window_start(eff_to)
    return eff_from, eff_to


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
    dates: DateRangeQuery = Depends(date_range_query),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
) -> TransactionSummaryRead:
    """Aggregate sums and counts over transactions using the same filters as ``GET /transactions``."""
    ca, da, cc, dc = TransactionService(db).transaction_summary(
        TransactionListParams(
            page=1,
            page_size=1,
            account_id=account_id,
            provider=provider,
            category=category,
            direction=direction,
            from_=dates.from_,
            to=dates.to,
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
    account_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    direction: Optional[Direction] = Query(None),
    dates: DateRangeQuery = Depends(date_range_query),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
) -> list[CashflowPoint]:
    """Monthly credit, debit, net, and counts; same filters as ``GET /transactions``.

    When both ``from`` and ``to`` are omitted, uses the last 12 calendar months through today.
    """
    eff_from, eff_to = _effective_cashflow_range(dates.from_, dates.to)
    return AnalyticsService(db).monthly_cashflow(
        TransactionListParams(
            page=1,
            page_size=1,
            account_id=account_id,
            provider=provider,
            category=category,
            direction=direction,
            from_=eff_from,
            to=eff_to,
            search=search,
        )
    )


@router.get("/category-breakdown", response_model=list[CategoryBreakdown])
async def category_breakdown(
    db: Session = Depends(get_db),
    month: Optional[str] = Query(None, description="Filter to a specific month (YYYY-MM)"),
    dates: DateRangeQuery = Depends(date_range_query),
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
    dates: DateRangeQuery = Depends(date_range_query),
    search: Optional[str] = Query(None, description="Search by merchant or payee"),
) -> list[MerchantSummary]:
    """Top payees by DEBIT ``amount_parsed``: group by merchant, else counterparty name, else ``__UNDEFINED__``.

    Same filters as ``GET /transactions`` except ``direction`` is ignored.
    """
    params = TransactionListParams(
        page=1,
        page_size=1,
        account_id=account_id,
        provider=provider,
        category=category,
        direction=None,
        from_=dates.from_,
        to=dates.to,
        search=search,
    )
    try:
        return AnalyticsService(db).top_merchants(
            params,
            limit=limit,
            month=month,
        )
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
