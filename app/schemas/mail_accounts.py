"""Schemas for mail accounts."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MailAccountCreate(BaseModel):
    """Payload to create a new mail account manually (rare; usually OAuth handles this)."""

    provider: str
    account_mail_id: Optional[str] = None
    token_json: Optional[str] = None
    is_active: bool = True
    is_primary: bool = False


class MailAccountRead(BaseModel):
    """Read representation of a mail account, safely omitting tokens."""

    id: int
    provider: str
    account_mail_id: Optional[str]
    is_active: bool
    is_primary: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
