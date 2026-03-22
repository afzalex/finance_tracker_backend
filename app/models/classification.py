"""ORM model: Classification rule (DB-driven email classifier)."""

import enum

from sqlalchemy import Boolean, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class MessageType(str, enum.Enum):
    TRANSACTION_ALERT = "TRANSACTION_ALERT"
    INVESTMENT_NOTICE = "INVESTMENT_NOTICE"
    STATEMENT = "STATEMENT"
    SINK = "SINK"
    OTHER = "OTHER"


class Classification(Base):
    """One row = one classification rule evaluated in descending priority order."""

    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), nullable=False)
    # Regex patterns — all non-empty must match
    sender_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    body_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    # Optional named-group extract regexes for additional metadata
    extract_regex: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
