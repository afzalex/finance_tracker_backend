"""ORM model: FetchedEmail — raw email cache."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class FetchedEmail(Base):
    """Raw email fetched from Gmail.

    Cached for offline re-processing (--offline flag) without hitting the API again.
    """

    __tablename__ = "fetched_emails"

    gmail_message_id: Mapped[str] = mapped_column(String, primary_key=True)  # natural PK
    thread_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_date_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Classification result stored alongside the raw email for debugging
    classification: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
