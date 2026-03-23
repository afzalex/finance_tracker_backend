"""ORM model: Classification rule (DB-driven email classifier)."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class MessageType(str, enum.Enum):
    """Category assigned to an email by the classifier.

    TRANSACTION_ALERT  — Bank debit/credit notification; sent to the parser.
    INVESTMENT_NOTICE  — Mutual fund / stock alert; sent to the parser.
    STATEMENT          — Monthly account statement; stored for future handling.
    SINK               — Newsletters, OTPs, promos; silently discarded.
    OTHER              — No rule matched; stored in the unparsed queue.
    """

    TRANSACTION_ALERT = "TRANSACTION_ALERT"
    INVESTMENT_NOTICE = "INVESTMENT_NOTICE"
    STATEMENT = "STATEMENT"
    SINK = "SINK"
    OTHER = "OTHER"


class Classification(Base):
    """One row = one classification rule, evaluated in descending priority order.

    All non-null match regexes must match for the rule to fire.
    The first matching rule wins.
    """

    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # Match regexes — all non-null must match
    sender_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    body_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Optional named-group extract regexes
    subject_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snippet_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
