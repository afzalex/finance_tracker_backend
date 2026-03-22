"""ORM model: Parser rule (DB-driven transaction parser)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Parser(Base):
    """One row = one parser that extracts transaction fields from a matching email.

    Match regexes identify which emails this parser handles.
    Extract regexes (with named groups) pull the transaction fields out.
    """

    __tablename__ = "parsers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)  # short tag e.g. "HDFC"
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # Match regexes — all non-null must match
    sender_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    body_match_regex: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Named-group extract regexes (txn_amount, txn_isdebit, txn_iscredit, txn_id, etc.)
    subject_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snippet_extract_regex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Date/time parsing format strings for txn_date / txn_time named groups
    txn_date_fmt: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    txn_time_fmt: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Default field values (overridden by named capture groups if present)
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    account_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sub_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
