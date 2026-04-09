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
    """DEBIT spend grouped by payee: trimmed ``merchant``, else trimmed ``counterparty_name``, else a sentinel."""

    merchant: str = Field(
        ...,
        description=(
            "Group key: non-empty trimmed ``merchant``, else non-empty trimmed ``counterparty_name``, "
            "else ``__UNDEFINED__``."
        ),
    )
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
    """Per calendar month: credit/debit sums, net, and transaction count."""

    month: str = Field(..., description="Calendar month in YYYY-MM (UTC/local stored ``transacted_at``).")
    credit: float = Field(..., ge=0, description="Sum of ``amount_parsed`` for CREDIT rows.")
    debit: float = Field(..., ge=0, description="Sum of ``amount_parsed`` for DEBIT rows.")
    total: float = Field(..., description="Net: ``credit - debit``.")
    count: int = Field(..., ge=0, description="Number of transactions in the month.")
