"""ORM model: FetchedEmail — raw email cache for offline re-processing."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class FetchedEmail(Base):
    """Stores the raw email payload fetched from Gmail.

    Used by ``--offline`` source flag to re-run the parse pipeline without
    hitting the Gmail API again.
    """

    __tablename__ = "fetched_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    sender: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
