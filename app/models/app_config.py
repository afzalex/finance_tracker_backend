"""DB-backed key/value entries for runtime config (ingest cursors, provider state, …).

Distinct from ``backend.config`` (environment / pydantic settings): this table persists
mutable values that change as the app runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AppConfig(Base):
    """One row per logical key; ``value`` is a string (ISO datetimes, ids, JSON, …)."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
