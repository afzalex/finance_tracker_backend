"""ORM model: classification/parser state for a fetched email (1:1 with fetched_emails)."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def _utc_naive_now() -> datetime:
    """Naive UTC for ``DateTime`` columns (SQLite + Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FetchedEmailEnrichment(Base):
    """Mutable enrichment for a raw row in ``fetched_emails``."""

    __tablename__ = "fetched_email_enrichments"

    fetched_email_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fetched_emails.id", ondelete="CASCADE"),
        primary_key=True,
    )
    classification_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    classification: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parser_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Milliseconds for last classify+parse pass on this mail.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        insert_default=_utc_naive_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        insert_default=_utc_naive_now,
    )
