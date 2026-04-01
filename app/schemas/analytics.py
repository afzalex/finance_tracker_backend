"""Stats and analytics response shapes."""

from __future__ import annotations

from pydantic import BaseModel


class MonthlyStats(BaseModel):
    """Debit/credit/net totals for a single calendar month."""

    month: str  # "YYYY-MM"
    total_debit: float
    total_credit: float
    net: float


class CategoryBreakdown(BaseModel):
    """Spending aggregated by transaction category for a time window."""

    category: str
    total: float
    transaction_count: int


class MerchantSummary(BaseModel):
    """Total spend and transaction count for a single merchant."""

    merchant: str
    total: float
    transaction_count: int


class CashflowPoint(BaseModel):
    """Income vs expense for a single calendar month (used in cashflow charts)."""

    month: str  # "YYYY-MM"
    income: float
    expense: float
