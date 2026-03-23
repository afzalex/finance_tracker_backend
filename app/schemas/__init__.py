"""Pydantic schemas for the Finance Tracker API.

Schemas are used by FastAPI for request/response validation and OpenAPI docs.
They are separate from ORM models to maintain a clean separation of concerns.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class Direction(str, Enum):
    """Money flow direction mirroring the ORM enum, exposed in API responses."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionBase(BaseModel):
    """Core transaction fields shared by request and response schemas."""

    provider: str
    account_id: str
    amount: float
    direction: Direction
    merchant: str | None = None
    category: str | None = None
    channel: str | None = None
    transaction_type: str | None = None
    sub_type: str | None = None
    account_type: str | None = None
    status: str | None = None
    txn_id: str | None = None
    transacted_at: datetime


class TransactionRead(TransactionBase):
    """Full transaction response including DB-assigned ``id`` and audit fields."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    gmail_message_id: str
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated wrapper returned by ``GET /api/v1/transactions``."""

    items: list[TransactionRead]
    total: int
    page: int
    page_size: int


# ── Account ───────────────────────────────────────────────────────────────────

class AccountRead(BaseModel):
    """Account/card/wallet summary returned by ``GET /api/v1/accounts``."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: str
    account_type: str | None = None
    display_name: str | None = None


# ── Stats / Analytics ─────────────────────────────────────────────────────────

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
