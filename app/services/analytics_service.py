"""Analytics service — cashflow, category breakdown, top merchants, etc."""

from __future__ import annotations

import calendar
import re
from dataclasses import replace
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import and_, case, desc, func, literal, or_, select
from sqlalchemy.orm import Session

from backend.app.constants import TOP_MERCHANTS_UNDEFINED_MERCHANT
from backend.app.models.transaction import Direction, Transaction
from backend.app.schemas.analytics import CashflowPoint, MerchantSummary
from backend.app.services.transaction_service import (
    TransactionListParams,
    _apply_transaction_filters,
)


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", month.strip())
    if not m:
        raise ValueError("month must be YYYY-MM")
    y, mo = int(m.group(1)), int(m.group(2))
    if mo < 1 or mo > 12:
        raise ValueError("invalid month")
    last = calendar.monthrange(y, mo)[1]
    start = datetime.combine(date(y, mo, 1), time.min)
    end = datetime.combine(date(y, mo, last), time.max)
    return start, end


class AnalyticsService:
    """Handles analytics aggregations over ``transactions``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def monthly_cashflow(self, params: TransactionListParams) -> list[CashflowPoint]:
        """Group filtered transactions by calendar month (YYYY-MM).

        Uses SQLite ``strftime`` on ``transacted_at`` (project default engine).
        """
        month_key = func.strftime("%Y-%m", Transaction.transacted_at).label("month")
        credit_amt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.CREDIT, Transaction.amount_parsed),
                    else_=literal(0.0),
                )
            ),
            0.0,
        ).label("credit")
        debit_amt = func.coalesce(
            func.sum(
                case(
                    (Transaction.direction == Direction.DEBIT, Transaction.amount_parsed),
                    else_=literal(0.0),
                )
            ),
            0.0,
        ).label("debit")
        cnt = func.count().label("cnt")
        stmt = select(month_key, credit_amt, debit_amt, cnt).select_from(Transaction)
        stmt = _apply_transaction_filters(stmt, params)
        stmt = stmt.group_by(month_key).order_by(month_key)
        rows = self.db.execute(stmt).all()
        out: list[CashflowPoint] = []
        for r in rows:
            cr = float(r.credit or 0.0)
            db_amt = float(r.debit or 0.0)
            out.append(
                CashflowPoint(
                    month=str(r.month),
                    credit=cr,
                    debit=db_amt,
                    total=cr - db_amt,
                    count=int(r.cnt or 0),
                )
            )
        return out

    def top_merchants(
        self,
        list_params: TransactionListParams,
        *,
        limit: int,
        month: Optional[str] = None,
        include_self_transfer: bool = False,
    ) -> list[MerchantSummary]:
        """DEBIT totals grouped by payee key; highest spend first.

        Bucket key is ``trim(merchant)`` when non-empty, else ``trim(counterparty_name)``,
        else ``TOP_MERCHANTS_UNDEFINED_MERCHANT``.

        ``list_params.direction`` is ignored so ranking always reflects outflows (DEBIT).

        * ``include_self_transfer`` false (default): omit rows where ``is_self_transfer`` is true
          (keep null/false / not-true).
        * ``include_self_transfer`` true: no filter on ``is_self_transfer`` (all DEBIT rows).
        """
        filter_params = replace(list_params, direction=None)
        trimmed_merchant = func.nullif(func.trim(Transaction.merchant), "")
        trimmed_counterparty = func.nullif(func.trim(Transaction.counterparty_name), "")
        payee_key = func.coalesce(
            trimmed_merchant,
            trimmed_counterparty,
            literal(TOP_MERCHANTS_UNDEFINED_MERCHANT),
        ).label("merchant")
        total_expr = func.sum(Transaction.amount_parsed).label("total")
        cnt_expr = func.count().label("cnt")
        self_tf_amt = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Transaction.direction == Direction.DEBIT,
                            Transaction.is_self_transfer.is_(True),
                        ),
                        Transaction.amount_parsed,
                    ),
                    else_=literal(0.0),
                )
            ),
            0.0,
        ).label("self_transfer_debit_total")
        self_tf_cnt = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Transaction.direction == Direction.DEBIT,
                            Transaction.is_self_transfer.is_(True),
                        ),
                        literal(1),
                    ),
                    else_=literal(0),
                )
            ),
            0,
        ).label("self_transfer_count")

        stmt = select(payee_key, total_expr, cnt_expr, self_tf_amt, self_tf_cnt).where(
            Transaction.direction == Direction.DEBIT
        )
        if not include_self_transfer:
            stmt = stmt.where(
                or_(
                    Transaction.is_self_transfer.is_(False),
                    Transaction.is_self_transfer.is_(None),
                )
            )
        stmt = stmt.group_by(payee_key)
        stmt = _apply_transaction_filters(stmt, filter_params)

        if month is not None:
            lo, hi = _month_bounds(month)
            stmt = stmt.where(Transaction.transacted_at >= lo, Transaction.transacted_at <= hi)

        stmt = stmt.order_by(desc(total_expr), payee_key).limit(limit)
        rows = self.db.execute(stmt).all()
        return [
            MerchantSummary(
                merchant=str(r.merchant),
                total=float(r.total or 0.0),
                transaction_count=int(r.cnt or 0),
                self_transfer_debit_total=float(r.self_transfer_debit_total or 0.0),
                self_transfer_count=int(r.self_transfer_count or 0),
            )
            for r in rows
        ]
