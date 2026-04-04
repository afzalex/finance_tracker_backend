"""ORM model: connected mail provider account (OAuth tokens, identity)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

# Stable string for Gmail implementation; other providers add their own constants.
MAIL_PROVIDER_GMAIL = "gmail"


class MailAccount(Base):
    """One row per linked mailbox (e.g. Gmail OAuth). ``token_json`` is ``Credentials.to_json()``."""

    __tablename__ = "mail_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "account_mail_id", name="uq_mail_accounts_provider_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_mail_id: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    token_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
