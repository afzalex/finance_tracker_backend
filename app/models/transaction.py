"""ORM model: Transaction."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Direction(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String, nullable=True)
    account_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    txn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    utr_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedup_signature: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    transacted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
