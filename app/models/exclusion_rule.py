"""ORM model: Exclusion rule."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ExclusionRule(Base):
    """One row = one exclusion rule.
    If a transaction's merchant or counterparty_name matches any payee in the rule, it is excluded.
    """

    __tablename__ = "exclusion_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # JSON string of list of payees (merchants/counterparties) to match against.
    payees: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Comma-separated parser IDs this rule applies to; empty/null = all parsers
    parser_ids: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
