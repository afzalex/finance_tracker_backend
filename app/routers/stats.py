"""Stats router — monthly debit/credit/net summary."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import MonthlyStats
from backend.database import get_db

router = APIRouter()


@router.get("", response_model=MonthlyStats)
async def monthly_stats(
    db: Session = Depends(get_db),
    month: str | None = Query(None, description="Month in YYYY-MM format (default: current month)"),
) -> MonthlyStats:
    """Return total debits, total credits, and net cashflow for a given month.

    TODO: Implement in StatsService.
    """
    raise NotImplementedError
