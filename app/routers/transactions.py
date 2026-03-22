"""Transactions router — paginated, filterable transaction list."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.schemas import TransactionListResponse
from backend.database import get_db

router = APIRouter()


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    account_id: str | None = Query(None),
    provider: str | None = Query(None),
    category: str | None = Query(None),
    direction: str | None = Query(None, pattern="^(DEBIT|CREDIT)$"),
    channel: str | None = Query(None),
    date_from: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    search: str | None = Query(None, description="Search by merchant or payee"),
    sort_by: str = Query("transacted_at", pattern="^(transacted_at|amount|merchant)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> TransactionListResponse:
    """Return a paginated, filtered list of all transactions.

    TODO: Implement query in TransactionService.
    """
    raise NotImplementedError
