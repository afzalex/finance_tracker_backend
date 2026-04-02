"""Schemas for runtime DB-backed app config (``app_config`` table)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AppConfigRead(BaseModel):
    key: str
    value: Optional[str]
    updated_at: datetime
    is_updatable: bool = Field(description="True iff key is in the ``app.*`` namespace.")


class AppConfigUpdate(BaseModel):
    value: Optional[str] = None

