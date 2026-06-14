"""Shared FastAPI query parameter types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from fastapi import Query


@dataclass(frozen=True)
class DateRangeQuery:
    from_: Optional[date]
    to: Optional[date]


def date_range_query(
    from_: Optional[date] = Query(
        None,
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive.",
    ),
    to: Optional[date] = Query(
        None,
        alias="to",
        description="End date (YYYY-MM-DD), inclusive end of day.",
    ),
) -> DateRangeQuery:
    return DateRangeQuery(from_=from_, to=to)
