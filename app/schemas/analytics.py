"""Stats and analytics response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class TransactionSummaryRead(BaseModel):
    """Credit/debit sums and counts for transactions matching the same filters as the list API."""

    credit_amount: float = Field(..., ge=0)
    debit_amount: float = Field(..., ge=0)
    amount: float = Field(..., description="Net: ``credit_amount - debit_amount``.")
    credit_count: int = Field(..., ge=0)
    debit_count: int = Field(..., ge=0)
    count: int = Field(..., ge=0, description="``credit_count + debit_count``.")


class CashflowPoint(BaseModel):
    """Income vs expense for a single calendar month (used in cashflow charts)."""

    month: str  # "YYYY-MM"
    income: float
    expense: float
