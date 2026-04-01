"""Pydantic schemas for the Finance Tracker API.

Schemas are used by FastAPI for request/response validation and OpenAPI docs.
They are separate from ORM models to maintain a clean separation of concerns.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Direction(str, Enum):
    """Money flow direction mirroring the ORM enum, exposed in API responses."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


# ── Rule enums (OpenAPI) ─────────────────────────────────────────────────────

class MessageType(str, Enum):
    TRANSACTION_ALERT = "TRANSACTION_ALERT"
    INVESTMENT_NOTICE = "INVESTMENT_NOTICE"
    STATEMENT = "STATEMENT"
    SINK = "SINK"
    OTHER = "OTHER"


class AccountType(str, Enum):
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"
    CREDIT_CARD = "CREDIT_CARD"
    WALLET = "WALLET"
    UPI = "UPI"


class TransactionType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    PAYMENT = "PAYMENT"
    CARD_SPEND = "CARD_SPEND"
    CARD_REPAYMENT = "CARD_REPAYMENT"
    UPI = "UPI"
    ATM = "ATM"
    NEFT = "NEFT"
    IMPS = "IMPS"
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class SubType(str, Enum):
    CARD_PAYMENT = "CARD_PAYMENT"
    CREDIT_CARD_REPAYMENT = "CREDIT_CARD_REPAYMENT"
    UPI_TRANSFER = "UPI_TRANSFER"
    UPI_RECEIVE = "UPI_RECEIVE"
    UPI_SEND = "UPI_SEND"
    NEFT_TRANSFER = "NEFT_TRANSFER"
    IMPS_TRANSFER = "IMPS_TRANSFER"
    ATM_WITHDRAWAL = "ATM_WITHDRAWAL"
    REFUND = "REFUND"
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    FEE = "FEE"
    REVERSAL = "REVERSAL"
    BILL_PAYMENT = "BILL_PAYMENT"
    LOAN_EMI = "LOAN_EMI"
    STANDING_ORDER = "STANDING_ORDER"
    DDA = "DDA"


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionBase(BaseModel):
    """Core transaction fields shared by request and response schemas."""

    provider: Optional[str] = None
    account_id: Optional[str] = None
    account_last4: Optional[str] = None
    card_last4: Optional[str] = None
    card_network: Optional[str] = None
    card_brand: Optional[str] = None
    amount: Optional[str] = None
    amount_parsed: float
    currency: str = "INR"
    direction: Direction
    merchant: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_vpa: Optional[str] = None
    counterparty_account: Optional[str] = None
    counterparty_number: Optional[str] = None
    counterparty_id: Optional[str] = None
    category: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    account_type: Optional[AccountType] = None
    status: Optional[Status] = None
    txn_id: Optional[str] = None
    fee_amount: Optional[float] = None
    balance: Optional[float] = None
    reward_points: Optional[float] = None
    parser_id: Optional[int] = None
    classification_id: Optional[int] = None
    transacted_at: datetime


class TransactionRead(TransactionBase):
    """Full transaction response including DB-assigned ``id`` and audit fields."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    mail_id: str
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated wrapper returned by ``GET /api/v1/transactions``."""

    items: list[TransactionRead]
    total: int
    page: int
    page_size: int


# ── Fetched email + enrichment ────────────────────────────────────────────────

class FetchedEmailEnrichmentRead(BaseModel):
    """Classification/parser state for one fetched email."""

    model_config = ConfigDict(from_attributes=True)
    fetched_email_id: int
    classification_id: Optional[int] = None
    classification: Optional[str] = None
    classification_reason: Optional[str] = None
    parser_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class FetchedEmailEnrichmentDetailRead(FetchedEmailEnrichmentRead):
    """Enrichment plus resolved rule names from ``classifications`` / ``parsers``."""

    classification_name: Optional[str] = None
    parser_name: Optional[str] = None


class FetchedEmailRead(BaseModel):
    """Raw cached email row (provider message id + body snapshot)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    mail_id: str
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    snippet: Optional[str] = None
    internal_date_ms: int
    body_text: str
    created_at: datetime


class FetchedEmailWithEnrichmentResponse(FetchedEmailRead):
    """``GET /api/v1/emails/{mail_id}`` — cached email row with optional nested enrichment."""

    enrichment: Optional[FetchedEmailEnrichmentDetailRead] = None


class UnparsedEmailListItem(BaseModel):
    """One entry in ``GET /api/v1/emails/unparsed`` — unparsed queue row plus ``mail_id`` / preview."""

    id: int
    fetched_email_id: int
    mail_id: str
    subject: Optional[str] = None
    snippet: Optional[str] = None
    reason: Optional[str] = None
    classification_id: Optional[int] = None
    parser_id: Optional[int] = None
    classification_name: Optional[str] = None
    parser_name: Optional[str] = None
    created_at: datetime


# ── Classification ────────────────────────────────────────────────────────────

class ClassificationRead(BaseModel):
    """One row from ``classifications`` (email classifier rule)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    message_type: MessageType
    priority: int = Field(..., ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ClassificationUpdate(BaseModel):
    """Partial update for ``PATCH /api/v1/classifications/{id}``. Omitted fields are unchanged."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1)
    message_type: Optional[MessageType] = None
    priority: Optional[int] = Field(None, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: Optional[bool] = None


class ClassificationCreate(BaseModel):
    """Create a classification rule (``POST /api/v1/classifications``)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    message_type: MessageType
    priority: int = Field(1, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: bool = True


class ParserRead(BaseModel):
    """One row from ``parsers`` (transaction extraction rule)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    label: str
    priority: int = Field(..., ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ParserUpdate(BaseModel):
    """Partial update for ``PATCH /api/v1/parsers/{id}``."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1)
    label: Optional[str] = Field(None, min_length=1)
    priority: Optional[int] = Field(None, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: Optional[bool] = None


class ParserCreate(BaseModel):
    """Create a parser rule (``POST /api/v1/parsers``)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    priority: int = Field(1, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: bool = True


# ── Account ───────────────────────────────────────────────────────────────────

class AccountRead(BaseModel):
    """Account/card/wallet summary returned by ``GET /api/v1/accounts``."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None


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
