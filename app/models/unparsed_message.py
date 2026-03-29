"""ORM model: UnparsedMessage — messages that failed classification or parsing.

Email content is not duplicated here; join to ``fetched_emails`` on ``fetched_email_id``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class UnparsedMessage(Base):
    """Tracks emails that could not be fully classified or parsed.

    Stores only the foreign key and failure metadata; the raw email content
    lives in ``fetched_emails``. Rows are removed when a subsequent ingest run
    successfully parses the message.
    """

    __tablename__ = "unparsed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_email_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fetched_emails.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    classification_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("classifications.id", ondelete="SET NULL"), nullable=True
    )
    parser_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("parsers.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
