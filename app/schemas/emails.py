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
    exclusion_rule_id: Optional[int] = None
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


class FetchedEmailContentRead(BaseModel):
    """Cached email content without enrichment (lighter response for match previews)."""

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


class MatcherPreviewRequest(BaseModel):
    """Match cached emails against subject/sender/body regexes.

    Provide ``mail_id`` to check exactly one cached message (returns ``matched``).
    Omit ``mail_id`` and set ``limit`` (1–10) to scan recent mail for up to ``limit`` matches.
    """

    mail_id: Optional[str] = None
    subject_match_regex: Optional[str] = None
    sender_match_regex: Optional[str] = None
    body_match_regex: Optional[str] = None
    limit: int = 3
    lookback_days: int = 30


class MatcherPreviewItemRead(BaseModel):
    """One preview row (includes ``body_text`` for client-side extract previews)."""

    mail_id: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    snippet: Optional[str] = None
    body_text: str
    internal_date_ms: int
    created_at: datetime


class MatcherPreviewResponse(BaseModel):
    """Matcher preview: either top-N matches or a single-mail match verdict."""

    items: list[MatcherPreviewItemRead]
    scanned: int
    mail_id: Optional[str] = None
    matched: Optional[bool] = None
    #: Full cached row (including ``body_text``) when ``mail_id`` was in the request.
    tested_mail: Optional[FetchedEmailContentRead] = None


class RegexSpanRead(BaseModel):
    """Inclusive start, exclusive end (Python ``Match.span``) in the haystack string."""

    start: int
    end: int


class RegexGroupSpanRead(BaseModel):
    """One capturing group that participated in the match (1-based ``index``)."""

    index: int
    name: Optional[str] = None
    start: int
    end: int


class RegexFieldPreviewRead(BaseModel):
    """Result of applying one optional extract regex to a haystack."""

    skipped: bool = False
    haystack: str = ""
    regex_error: Optional[str] = None
    matched: Optional[bool] = None
    extracted_value: Optional[str] = None
    full_match: Optional[RegexSpanRead] = None
    groups: list[RegexGroupSpanRead] = []


class ExtractRegexPreviewRequest(BaseModel):
    """Evaluate extract regexes against one cached mail (by provider ``mail_id``)."""

    mail_id: str
    subject_extract_regex: Optional[str] = None
    body_extract_regex: Optional[str] = None
    snippet_extract_regex: Optional[str] = None


class ExtractRegexPreviewResponse(BaseModel):
    """Match spans for UI highlighting; body haystack mirrors parser preview (body, else snippet)."""

    mail_id: str
    subject: RegexFieldPreviewRead
    body: RegexFieldPreviewRead
    snippet: RegexFieldPreviewRead


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
