"""ORM model: Parser rule (DB-driven transaction parser)."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Parser(Base):
    """One row = one parser rule that extracts transaction fields from an email."""

    __tablename__ = "parsers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Regexes to identify which emails this parser handles
    sender_match_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_match_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    body_match_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    # Named-group extract regexes for transaction fields
    extract_regex: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Default values (override by named captures)
    default_transaction_type: Mapped[str | None] = mapped_column(String, nullable=True)
    default_sub_type: Mapped[str | None] = mapped_column(String, nullable=True)
    default_account_type: Mapped[str | None] = mapped_column(String, nullable=True)
    default_status: Mapped[str | None] = mapped_column(String, nullable=True)
    default_category: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
