"""ORM model: classification/parser state for a fetched email (1:1 with fetched_emails)."""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


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
