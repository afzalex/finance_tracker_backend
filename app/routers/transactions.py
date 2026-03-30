"""Transactions router — paginated, filterable transaction list."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import Direction, TransactionListResponse
from backend.app.services.transaction_service import TransactionListParams, TransactionService
from backend.database import get_db

router = APIRouter()


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

    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)
