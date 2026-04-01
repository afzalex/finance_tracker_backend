"""Classification (email routing) rule schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import MessageType


class ClassificationRead(BaseModel):
    """One row from ``classifications`` (email classifier rule)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    message_type: MessageType
    priority: int = Field(..., ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ClassificationUpdate(BaseModel):
    """Partial update for ``PATCH /api/v1/classifications/{id}``. Omitted fields are unchanged."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1)
    message_type: Optional[MessageType] = None
    priority: Optional[int] = Field(None, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: Optional[bool] = None


class ClassificationCreate(BaseModel):
    """Create a classification rule (``POST /api/v1/classifications``)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    message_type: MessageType
    priority: int = Field(1, ge=1, le=100)
    sender_match_regex: Optional[str] = None
    subject_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None
    is_active: bool = True
