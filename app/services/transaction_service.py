"""Transaction service — query logic for the /transactions endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from sqlalchemy import and_, asc, case, desc, func, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from backend.app.constants import DISTINCT_UNNAMED_COUNTERPARTY
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
    counterparty: str | None = None
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


def _distinct_date_clauses(date_from: date | None, date_to: date | None) -> list:
    """``transacted_at`` bounds for distinct-catalog queries (inclusive days)."""
    clauses: list = []
    if date_from is not None:
        clauses.append(Transaction.transacted_at >= _day_start(date_from))
    if date_to is not None:
        clauses.append(Transaction.transacted_at <= _day_end(date_to))
    return clauses


def _apply_transaction_filters(stmt: Select, params: TransactionListParams) -> Select:
    """WHERE clauses shared by list and summary queries (ignores sort/pagination)."""
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
    if params.counterparty:
        cp = params.counterparty.strip()
        if cp == DISTINCT_UNNAMED_COUNTERPARTY:
            # Rows with both ``counterparty_name`` and ``merchant`` null (no trimmed fallback).
            stmt = stmt.where(
                and_(
                    Transaction.counterparty_name.is_(None),
                    Transaction.merchant.is_(None),
                )
            )
        elif cp:
            stmt = stmt.where(
                or_(
                    func.trim(Transaction.counterparty_name) == cp,
                    func.trim(Transaction.merchant) == cp,
                )
            )
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
    return stmt


class TransactionService:
    """Handles all transaction retrieval queries.

    Read-only API surface. Writes are performed by ingestion.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _distinct_trimmed_strings(
        self,
        column,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> set[str]:
        stmt = select(column).where(column.isnot(None))
        for clause in _distinct_date_clauses(date_from, date_to):
            stmt = stmt.where(clause)
        stmt = stmt.distinct()
        rows = self.db.scalars(stmt).all()
        return {str(v).strip() for v in rows if v is not None and str(v).strip()}

    def _has_unnamed_merchant_rows(
        self, *, date_from: date | None = None, date_to: date | None = None
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(or_(Transaction.merchant.is_(None), func.trim(Transaction.merchant) == ""))
        )
        for clause in _distinct_date_clauses(date_from, date_to):
            stmt = stmt.where(clause)
        n = self.db.scalar(stmt)
        return (n or 0) > 0

    def _has_unnamed_counterparty_rows(
        self, *, date_from: date | None = None, date_to: date | None = None
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(
                or_(
                    Transaction.counterparty_name.is_(None),
                    func.trim(Transaction.counterparty_name) == "",
                )
            )
        )
        for clause in _distinct_date_clauses(date_from, date_to):
            stmt = stmt.where(clause)
        n = self.db.scalar(stmt)
        return (n or 0) > 0

    def _has_self_transfer_rows(
        self, *, date_from: date | None = None, date_to: date | None = None
    ) -> bool:
        stmt = select(func.count()).select_from(Transaction).where(Transaction.is_self_transfer.is_(True))
        for clause in _distinct_date_clauses(date_from, date_to):
            stmt = stmt.where(clause)
        n = self.db.scalar(stmt)
        return (n or 0) > 0

    def distinct_catalog(
        self,
        *,
        include_merchants_in_counterparties: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[str], list[str], list[str], bool]:
        """Return sorted unique providers, merchants, counterparties, and self-transfer flag.

        When ``date_from`` / ``date_to`` are set, only transactions in that ``transacted_at`` range
        (inclusive calendar days) are considered — same semantics as ``GET /transactions``.

        When some rows have no counterparty name, or no merchant (null/blank) so display falls back,
        ``DISTINCT_UNNAMED_COUNTERPARTY`` may be added to ``counterparties`` for filtering those rows.
        """
        providers = sorted(self._distinct_trimmed_strings(Transaction.provider, date_from=date_from, date_to=date_to))
        merchants_set = self._distinct_trimmed_strings(Transaction.merchant, date_from=date_from, date_to=date_to)
        merchants = sorted(merchants_set)

        counterparty_set = self._distinct_trimmed_strings(
            Transaction.counterparty_name, date_from=date_from, date_to=date_to
        )
        if self._has_unnamed_counterparty_rows(date_from=date_from, date_to=date_to) or self._has_unnamed_merchant_rows(
            date_from=date_from, date_to=date_to
        ):
            counterparty_set = counterparty_set | {DISTINCT_UNNAMED_COUNTERPARTY}

        if include_merchants_in_counterparties:
            counterparties = sorted(counterparty_set | set(merchants))
        else:
            counterparties = sorted(counterparty_set)

        has_self_transfer = self._has_self_transfer_rows(date_from=date_from, date_to=date_to)
        return providers, merchants, counterparties, has_self_transfer

    def list_transactions(self, params: TransactionListParams):
        stmt = _apply_transaction_filters(select(Transaction), params)

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

    def transaction_summary(self, params: TransactionListParams) -> tuple[float, float, int, int]:
        """Return (credit_amount, debit_amount, credit_count, debit_count) for filtered rows."""
        credit_amt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.CREDIT, Transaction.amount_parsed),
                    else_=literal(0.0),
                )
            ),
            0.0,
        )
        debit_amt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.DEBIT, Transaction.amount_parsed),
                    else_=literal(0.0),
                )
            ),
            0.0,
        )
        credit_cnt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.CREDIT, literal(1)),
                    else_=literal(0),
                )
            ),
            0,
        )
        debit_cnt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.DEBIT, literal(1)),
                    else_=literal(0),
                )
            ),
            0,
        )
        stmt = select(credit_amt, debit_amt, credit_cnt, debit_cnt).select_from(Transaction)
        stmt = _apply_transaction_filters(stmt, params)
        row = self.db.execute(stmt).one()
        return (
            float(row[0] or 0.0),
            float(row[1] or 0.0),
            int(row[2] or 0),
            int(row[3] or 0),
        )

    def update_transaction_is_self_transfer(
        self, transaction_id: int, *, is_self_transfer: bool
    ) -> Transaction | None:
        """Set ``is_self_transfer`` on the row; returns ``None`` if id is missing.

        Caller must ``commit`` (and optionally ``refresh``) the session.
        """
        txn = self.db.get(Transaction, transaction_id)
        if txn is None:
            return None
        txn.is_self_transfer = bool(is_self_transfer)
        return txn
