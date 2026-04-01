"""Account summary schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class AccountRead(BaseModel):
    """Account/card/wallet summary returned by ``GET /api/v1/accounts``."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None
