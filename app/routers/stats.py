"""Stats router — monthly debit/credit/net summary."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import MonthlyStats
from backend.database import get_db

router = APIRouter()


@router.get("", response_model=MonthlyStats)
async def monthly_stats(
    db: Session = Depends(get_db),
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (default: current month)"),
) -> MonthlyStats:
    """Return total debits, total credits, and net cashflow for a given month.

    TODO: Implement in StatsService.
    """
    raise NotImplementedError
