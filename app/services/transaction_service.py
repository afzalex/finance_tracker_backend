"""Transaction service — query logic for the /transactions endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.transaction import Direction, Transaction


@dataclass(frozen=True)
class TransactionListParams:
    page: int = 1
    page_size: int = 50
    account_id: str | None = None
    provider: str | None = None
    category: str | None = None
    direction: Direction | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = None
    sort_by: str = (
        "transacted_at"
    )  # transacted_at|amount|merchant|provider|account_id|transaction_type|counterparty
    sort_order: str = "desc"  # asc|desc


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _day_end(d: date) -> datetime:
    # Inclusive end-of-day boundary.
    return datetime.combine(d, time.max)


class TransactionService:
    """Handles all transaction retrieval queries.

    Read-only API surface. Writes are performed by ingestion.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _distinct_trimmed_strings(self, column) -> set[str]:
        rows = self.db.scalars(select(column).where(column.isnot(None)).distinct()).all()
        return {str(v).strip() for v in rows if v is not None and str(v).strip()}

    def distinct_catalog(self, *, include_merchants_in_counterparties: bool = False) -> tuple[list[str], list[str], list[str]]:
        """Return sorted unique providers, merchants, and counterparty names from ``transactions``."""
        providers = sorted(self._distinct_trimmed_strings(Transaction.provider))
        merchants = sorted(self._distinct_trimmed_strings(Transaction.merchant))
        counterparty_names = self._distinct_trimmed_strings(Transaction.counterparty_name)
        if include_merchants_in_counterparties:
            counterparties = sorted(counterparty_names | self._distinct_trimmed_strings(Transaction.merchant))
        else:
            counterparties = sorted(counterparty_names)
        return providers, merchants, counterparties

    def list_transactions(self, params: TransactionListParams):
        stmt = select(Transaction)

        if params.account_id:
            stmt = stmt.where(Transaction.account_id == params.account_id)
        if params.provider:
            stmt = stmt.where(Transaction.provider == params.provider)
        if params.category:
            stmt = stmt.where(Transaction.category == params.category)
        if params.direction:
            stmt = stmt.where(Transaction.direction == params.direction)
        if params.date_from:
            stmt = stmt.where(Transaction.transacted_at >= _day_start(params.date_from))
        if params.date_to:
            stmt = stmt.where(Transaction.transacted_at <= _day_end(params.date_to))

        if params.search:
            q = params.search.strip()
            if q:
                like = f"%{q.lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Transaction.merchant).like(like),
                        func.lower(Transaction.counterparty_name).like(like),
                    )
                )

        sort_col = Transaction.transacted_at
        if params.sort_by == "amount":
            sort_col = Transaction.amount_parsed
        elif params.sort_by == "merchant":
            sort_col = Transaction.merchant
        elif params.sort_by == "provider":
            sort_col = Transaction.provider
        elif params.sort_by == "account_id":
            sort_col = Transaction.account_id
        elif params.sort_by == "transaction_type":
            sort_col = Transaction.transaction_type
        elif params.sort_by == "counterparty":
            sort_col = func.coalesce(
                Transaction.counterparty_name,
                Transaction.merchant,
            )

        order_fn = desc if params.sort_order == "desc" else asc
        stmt = stmt.order_by(order_fn(sort_col), desc(Transaction.id))

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

        offset = (params.page - 1) * params.page_size
        items = list(self.db.scalars(stmt.offset(offset).limit(params.page_size)).all())

        return items, total
