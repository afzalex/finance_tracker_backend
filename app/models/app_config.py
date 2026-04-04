"""DB-backed key/value entries for runtime config (ingest cursors, provider state, …).

Distinct from ``backend.config`` (environment / pydantic settings): this table persists
mutable values that change as the app runs.

``mail_account_id`` scopes a row to a linked mailbox; ``0`` means system-wide / default
(not tied to a specific ``mail_accounts`` row).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

# Sentinel: config not scoped to a specific row in ``mail_accounts``.
APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID = 0


class AppConfig(Base):
    """One row per (mail_account_id, logical key); ``value`` is a string."""

    __tablename__ = "app_config"
    __table_args__ = (
        UniqueConstraint("mail_account_id", "key", name="uq_app_config_mail_account_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_account_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
