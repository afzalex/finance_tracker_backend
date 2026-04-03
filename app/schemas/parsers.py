"""Parser (transaction extraction) rule schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import AccountType, Status, SubType, TransactionType


class ParserRead(BaseModel):
    """One row from ``parsers`` (transaction extraction rule)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    label: str
    priority: int = Field(..., ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    mail_count: int = Field(
        0,
        ge=0,
        description="Rows in ``fetched_email_enrichments`` with this ``parser_id``.",
    )


class ParserUpdate(BaseModel):
    """Partial update for ``PATCH /api/v1/parsers/{id}``."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1)
    label: Optional[str] = Field(None, min_length=1)
    priority: Optional[int] = Field(None, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: Optional[bool] = None


class ParserCreate(BaseModel):
    """Create a parser rule (``POST /api/v1/parsers``)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    priority: int = Field(1, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    txn_date_fmt: Optional[str] = None
    txn_time_fmt: Optional[str] = None
    provider: Optional[str] = None
    account_type: Optional[AccountType] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    status: Optional[Status] = None
    is_active: bool = True
