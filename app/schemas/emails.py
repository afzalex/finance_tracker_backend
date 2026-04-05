"""Fetched-email cache + unparsed queue API shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FetchedEmailEnrichmentRead(BaseModel):
    """Classification/parser state for one fetched email."""

    model_config = ConfigDict(from_attributes=True)
    fetched_email_id: int
    classification_id: Optional[int] = None
    classification: Optional[str] = None
    classification_reason: Optional[str] = None
    parser_id: Optional[int] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class FetchedEmailEnrichmentDetailRead(FetchedEmailEnrichmentRead):
    """Enrichment plus resolved rule names from ``classifications`` / ``parsers``."""

    classification_name: Optional[str] = None
    parser_name: Optional[str] = None


class FetchedEmailRead(BaseModel):
    """Raw cached email row (provider message id + body snapshot)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    mail_id: str
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    snippet: Optional[str] = None
    internal_date_ms: int
    body_text: str
    created_at: datetime


class FetchedEmailWithEnrichmentResponse(FetchedEmailRead):
    """``GET /api/v1/emails/{mail_id}`` — cached email row with optional nested enrichment."""

    enrichment: Optional[FetchedEmailEnrichmentDetailRead] = None


class FetchedEmailWithLinkedTransactionsRead(FetchedEmailRead):
    """Cached email with enrichment and at least one ledger row for the same ``mail_id``."""

    enrichment: FetchedEmailEnrichmentDetailRead
    last_transacted_at: datetime
    transaction_count: int


class UnparsedEmailListItem(BaseModel):
    """One entry in ``GET /api/v1/emails/unparsed`` — queue row, ``mail_id`` / subject, and enrichment summary.

    ``classification_reason`` comes from ``fetched_email_enrichments`` when present. Body and snippet are omitted.
    """

    id: int
    fetched_email_id: int
    mail_id: str
    subject: Optional[str] = None
    mail_received_at: Optional[datetime] = None
    classification_reason: Optional[str] = None
    reason: Optional[str] = None
    classification_id: Optional[int] = None
    parser_id: Optional[int] = None
    classification_name: Optional[str] = None
    parser_name: Optional[str] = None
    created_at: datetime


class UnparsedEmailDetailRead(BaseModel):
    """``GET /api/v1/emails/unparsed/{id}`` — unparsed queue metadata plus full cached email and enrichment."""

    id: int
    reason: Optional[str] = None
    classification_id: Optional[int] = None
    parser_id: Optional[int] = None
    classification_name: Optional[str] = None
    parser_name: Optional[str] = None
    created_at: datetime
    email: FetchedEmailRead
    enrichment: Optional[FetchedEmailEnrichmentDetailRead] = None
