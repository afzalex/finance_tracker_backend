"""ORM model: IngestCursor — persists the Gmail history ID between runs."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class IngestCursor(Base):
    """Single-row table that stores the cursor used by incremental ingest runs."""

    __tablename__ = "ingest_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_history_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
