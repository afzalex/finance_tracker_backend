"""Analytics service — cashflow, category breakdown, top merchants, etc."""

from __future__ import annotations

import calendar
import re
from dataclasses import replace
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.models.transaction import Direction, Transaction
from backend.app.schemas.analytics import MerchantSummary
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

    def top_merchants(
        self,
        list_params: TransactionListParams,
        *,
        limit: int,
        month: Optional[str] = None,
    ) -> list[MerchantSummary]:
        """DEBIT totals by trimmed ``merchant`` for filtered rows; highest spend first.

        ``list_params.direction`` is ignored so ranking always reflects outflows (DEBIT).
        """
        filter_params = replace(list_params, direction=None)
        mkey = func.trim(Transaction.merchant)
        total_expr = func.sum(Transaction.amount_parsed).label("total")
        cnt_expr = func.count().label("cnt")

        stmt = (
            select(mkey.label("merchant"), total_expr, cnt_expr)
            .where(
                Transaction.merchant.isnot(None),
                mkey != "",
                Transaction.direction == Direction.DEBIT,
            )
            .group_by(mkey)
        )
        stmt = _apply_transaction_filters(stmt, filter_params)

        if month is not None:
            lo, hi = _month_bounds(month)
            stmt = stmt.where(Transaction.transacted_at >= lo, Transaction.transacted_at <= hi)

        stmt = stmt.order_by(desc(total_expr), mkey).limit(limit)
        rows = self.db.execute(stmt).all()
        return [
            MerchantSummary(
                merchant=str(r.merchant),
                total=float(r.total or 0.0),
                transaction_count=int(r.cnt or 0),
            )
            for r in rows
        ]
