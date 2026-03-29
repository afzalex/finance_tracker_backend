"""ORM model: Transaction."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Direction(str, enum.Enum):
    """Money flow direction from the account holder's perspective."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Origin(str, enum.Enum):
    """How the transaction was discovered."""

    EMAIL_ALERT = "EMAIL_ALERT"   # Parsed from a bank notification email
    STATEMENT = "STATEMENT"        # Imported from a monthly PDF/CSV statement


class Transaction(Base):
    """A single financial transaction parsed from a bank alert email.

    The ``provider`` + ``txn_id`` pair forms a unique constraint to prevent
    duplicate rows when the same bank reference number appears in multiple emails.
    ``amount`` stores the raw regex capture for auditing; ``amount_parsed`` is
    the float used for all calculations.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Source ────────────────────────────────────────────────────────────────
    mail_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    transacted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    origin: Mapped[Origin] = mapped_column(Enum(Origin), nullable=False)

    # ── Amount ────────────────────────────────────────────────────────────────
    amount: Mapped[Optional[str]] = mapped_column(String, nullable=True)          # raw string from regex
    amount_parsed: Mapped[float] = mapped_column(Float, nullable=False)           # numeric for calculations
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)

    # ── Provider / Account ────────────────────────────────────────────────────
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)  # e.g. HDFC, ICICI
    account_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)    # SAVINGS, CREDIT_CARD, …
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    account_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    card_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    card_network: Mapped[Optional[str]] = mapped_column(String, nullable=True)    # VISA, MASTERCARD
    card_brand: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Transaction metadata ──────────────────────────────────────────────────
    transaction_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sub_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fee_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Merchant / Counterparty ───────────────────────────────────────────────
    merchant: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    counterparty_vpa: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # UPI VPA
    counterparty_account: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    counterparty_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    counterparty_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Categorisation ────────────────────────────────────────────────────────
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Financial extras ─────────────────────────────────────────────────────
    balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reward_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Parser / classifier traceability ─────────────────────────────────────
    parser_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    classification_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "txn_id", name="uq_provider_txn_id"),
        Index("idx_transactions_category", "category"),
    )
