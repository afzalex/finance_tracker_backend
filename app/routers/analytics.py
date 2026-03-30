"""Analytics router — charts and breakdowns for the dashboard."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import CategoryBreakdown, CashflowPoint, MerchantSummary
from backend.database import get_db

router = APIRouter()


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
    month: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> list[MerchantSummary]:
    """Top merchants by total spend.

    TODO: Implement in AnalyticsService.
    """
    raise NotImplementedError


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
