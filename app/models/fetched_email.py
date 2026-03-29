"""ORM model: FetchedEmail — raw email cache (insert-only from the pipeline)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class FetchedEmail(Base):
    """Raw email from a provider (Gmail today; others later).

    ``id`` is the internal primary key. ``mail_id`` is the provider's stable
    message identifier (e.g. Gmail API message id). Rows are inserted once per
    ``mail_id``; updates are not applied. Classification/parser state lives in
    ``FetchedEmailEnrichment``.
    """

    __tablename__ = "fetched_emails"
    __table_args__ = (UniqueConstraint("mail_id", name="uq_fetched_emails_mail_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_date_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
