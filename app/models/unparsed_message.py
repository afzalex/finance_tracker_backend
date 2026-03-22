"""ORM model: UnparsedMessage — messages that failed classification or parsing.

Email content is not duplicated here; join to fetched_emails on gmail_message_id for the full payload.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class UnparsedMessage(Base):
    __tablename__ = "unparsed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(
        String, ForeignKey("fetched_emails.gmail_message_id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Traceability: which classifier / parser tried this message
    classification_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("classifications.id", ondelete="SET NULL"), nullable=True
    )
    parser_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("parsers.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
