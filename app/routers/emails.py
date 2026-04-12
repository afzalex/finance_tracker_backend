"""Cached email bodies + classifier/parser enrichment (read-only).

Lookup is always by **provider message id** (``FetchedEmail.mail_id``), not by the internal
surrogate ``FetchedEmail.id`` (the response includes ``id`` at the top level for that row).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.classification import Classification
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.parser import Parser
from backend.app.models.unparsed_message import UnparsedMessage
from backend.app.schemas import (
    ExtractRegexPreviewRequest,
    ExtractRegexPreviewResponse,
    FetchedEmailContentRead,
    FetchedEmailEnrichmentDetailRead,
    FetchedEmailRead,
    FetchedEmailWithEnrichmentResponse,
    FetchedEmailWithLinkedTransactionsRead,
    MatcherPreviewItemRead,
    MatcherPreviewRequest,
    MatcherPreviewResponse,
    RegexFieldPreviewRead,
    UnparsedEmailDetailRead,
    UnparsedEmailListItem,
)
from backend.app.services.fetched_email_service import (
    list_top_emails_with_transaction_and_enrichment,
)
from backend.app.services.regex_preview import regex_field_preview
from backend.database import get_db
from backend.ingestion.pipeline import reprocess_one_from_fetched

router = APIRouter()


def _compile_optional_regex(value: str | None, field: str) -> re.Pattern[str] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return re.compile(raw)
    except re.error as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field} regex: {exc}") from exc


def _matches(rx: re.Pattern[str] | None, text: str | None) -> bool:
    if rx is None:
        return True
    return bool(rx.search(text or ""))


def _all_match(
    *,
    subject_rx: re.Pattern[str] | None,
    sender_rx: re.Pattern[str] | None,
    body_rx: re.Pattern[str] | None,
    email: FetchedEmail,
) -> bool:
    return (
        _matches(subject_rx, email.subject)
        and _matches(sender_rx, email.sender)
        and _matches(body_rx, email.body_text)
    )


def _matcher_preview_item(email: FetchedEmail) -> MatcherPreviewItemRead:
    return MatcherPreviewItemRead(
        mail_id=email.mail_id,
        subject=email.subject,
        sender=email.sender,
        snippet=email.snippet,
        body_text=email.body_text or "",
        internal_date_ms=email.internal_date_ms,
        created_at=email.created_at,
    )


def _enrichment_detail(
    db: Session, enrichment: FetchedEmailEnrichment
) -> FetchedEmailEnrichmentDetailRead:
    c_name = None
    p_name = None
    if enrichment.classification_id is not None:
        cl = db.get(Classification, enrichment.classification_id)
        c_name = cl.name if cl else None
    if enrichment.parser_id is not None:
        pr = db.get(Parser, enrichment.parser_id)
        p_name = pr.name if pr else None
    return FetchedEmailEnrichmentDetailRead(
        fetched_email_id=enrichment.fetched_email_id,
        classification_id=enrichment.classification_id,
        classification=enrichment.classification,
        classification_reason=enrichment.classification_reason,
        parser_id=enrichment.parser_id,
        processing_time_ms=enrichment.processing_time_ms,
        created_at=enrichment.created_at,
        updated_at=enrichment.updated_at,
        classification_name=c_name,
        parser_name=p_name,
    )


def _mail_received_at_utc(internal_date_ms: int) -> datetime | None:
    if internal_date_ms <= 0:
        return None
    return datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)


def _utc_day_start_ms(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp() * 1000)


def _utc_day_end_ms(d: date) -> int:
    return int(datetime.combine(d, time.max, tzinfo=timezone.utc).timestamp() * 1000)


def _rule_name(db: Session, classification_id: int | None, parser_id: int | None) -> tuple[str | None, str | None]:
    c_name = None
    p_name = None
    if classification_id is not None:
        cl = db.get(Classification, classification_id)
        c_name = cl.name if cl else None
    if parser_id is not None:
        pr = db.get(Parser, parser_id)
        p_name = pr.name if pr else None
    return c_name, p_name


@router.get(
    "/by-id/{fetched_email_id}",
    response_model=FetchedEmailWithEnrichmentResponse,
    summary="Get cached email by internal row id",
)
async def get_email_by_surrogate_id(
    fetched_email_id: int = Path(..., ge=1, description="Surrogate PK ``fetched_emails.id``"),
    db: Session = Depends(get_db),
) -> FetchedEmailWithEnrichmentResponse:
    """Return one cached email and its enrichment (same shape as ``GET /{mail_id}``)."""
    email = db.get(FetchedEmail, fetched_email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    enrichment = db.get(FetchedEmailEnrichment, email.id)
    base = FetchedEmailRead.model_validate(email)
    return FetchedEmailWithEnrichmentResponse(
        **base.model_dump(),
        enrichment=_enrichment_detail(db, enrichment) if enrichment else None,
    )


@router.get(
    "/unparsed",
    response_model=list[UnparsedEmailListItem],
    summary="List emails in the unparsed queue",
)
async def list_unparsed_emails(
    db: Session = Depends(get_db),
    from_date: Optional[date] = Query(
        None,
        alias="from",
        description="Only rows whose mail ``internal_date_ms`` is on or after this UTC date.",
    ),
    to_date: Optional[date] = Query(
        None,
        alias="to",
        description="Only rows whose mail ``internal_date_ms`` is on or before this UTC date (end of day).",
    ),
    date_from: Optional[date] = Query(None, description="Same as ``from``."),
    date_to: Optional[date] = Query(None, description="Same as ``to``."),
) -> list[UnparsedEmailListItem]:
    """Return unparsed rows with ``mail_id``, subject, ``mail_received_at`` (UTC from provider internal ms), and optional ``classification_reason`` from enrichment (newest first). Omits body and snippet."""
    eff_from = from_date or date_from
    eff_to = to_date or date_to
    stmt = (
        select(UnparsedMessage, FetchedEmail, FetchedEmailEnrichment)
        .join(FetchedEmail, UnparsedMessage.fetched_email_id == FetchedEmail.id)
        .outerjoin(FetchedEmailEnrichment, FetchedEmailEnrichment.fetched_email_id == FetchedEmail.id)
    )
    if eff_from is not None:
        stmt = stmt.where(FetchedEmail.internal_date_ms >= _utc_day_start_ms(eff_from))
    if eff_to is not None:
        stmt = stmt.where(FetchedEmail.internal_date_ms <= _utc_day_end_ms(eff_to))
    stmt = stmt.order_by(UnparsedMessage.created_at.desc(), UnparsedMessage.id.desc())
    rows = db.execute(stmt).all()
    out: list[UnparsedEmailListItem] = []
    for um, fe, enr in rows:
        c_name, p_name = _rule_name(db, um.classification_id, um.parser_id)
        out.append(
            UnparsedEmailListItem(
                id=um.id,
                fetched_email_id=um.fetched_email_id,
                mail_id=fe.mail_id,
                subject=fe.subject,
                mail_received_at=_mail_received_at_utc(fe.internal_date_ms),
                classification_reason=enr.classification_reason if enr else None,
                reason=um.reason,
                classification_id=um.classification_id,
                parser_id=um.parser_id,
                classification_name=c_name,
                parser_name=p_name,
                created_at=um.created_at,
            )
        )
    return out


@router.get(
    "/unparsed/{unparsed_message_id}",
    response_model=UnparsedEmailDetailRead,
    summary="Get one unparsed queue row with full cached email and enrichment",
)
async def get_unparsed_email_detail(
    unparsed_message_id: int = Path(..., ge=1, description="Primary key of ``unparsed_messages``"),
    db: Session = Depends(get_db),
) -> UnparsedEmailDetailRead:
    """Return queue metadata plus nested ``FetchedEmailRead`` and optional enrichment (same enrichment shape as ``GET /{mail_id}``)."""
    um = db.get(UnparsedMessage, unparsed_message_id)
    if um is None:
        raise HTTPException(status_code=404, detail="Unparsed message not found")
    fe = db.get(FetchedEmail, um.fetched_email_id)
    if fe is None:
        raise HTTPException(status_code=404, detail="Fetched email not found")
    c_name, p_name = _rule_name(db, um.classification_id, um.parser_id)
    enrichment = db.get(FetchedEmailEnrichment, fe.id)
    return UnparsedEmailDetailRead(
        id=um.id,
        reason=um.reason,
        classification_id=um.classification_id,
        parser_id=um.parser_id,
        classification_name=c_name,
        parser_name=p_name,
        created_at=um.created_at,
        email=FetchedEmailRead.model_validate(fe),
        enrichment=_enrichment_detail(db, enrichment) if enrichment else None,
    )


@router.get(
    "/top-with-transactions",
    response_model=list[FetchedEmailWithLinkedTransactionsRead],
    summary="Cached emails with enrichment that have ledger rows",
)
async def top_emails_with_transactions(
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=10, description="Number of rows (max 10)."),
) -> list[FetchedEmailWithLinkedTransactionsRead]:
    """Most recently transacted ``mail_id`` first (by ``transactions.transacted_at``)."""
    rows = list_top_emails_with_transaction_and_enrichment(db, limit=limit)
    out: list[FetchedEmailWithLinkedTransactionsRead] = []
    for fe, enr, last_at, txn_count in rows:
        base = FetchedEmailRead.model_validate(fe)
        out.append(
            FetchedEmailWithLinkedTransactionsRead(
                **base.model_dump(),
                enrichment=_enrichment_detail(db, enr),
                last_transacted_at=last_at,
                transaction_count=int(txn_count),
            )
        )
    return out


@router.post(
    "/{mail_id}/reprocess",
    summary="Re-process one cached email by mail_id (offline)",
)
async def reprocess_email_by_mail_id(
    mail_id: str = Path(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run classification + parsing for a single cached email (no Gmail fetch)."""
    try:
        stats = reprocess_one_from_fetched(db, mail_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Email not found") from None
    return {"mail_id": mail_id, "stats": stats}


@router.get(
    "/{mail_id}/content",
    response_model=FetchedEmailContentRead,
    summary="Get cached email content by mail_id (no enrichment)",
)
async def get_email_content_by_mail_id(
    mail_id: str = Path(..., min_length=1),
    db: Session = Depends(get_db),
) -> FetchedEmailContentRead:
    email = db.execute(select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)).scalar_one_or_none()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return FetchedEmailContentRead.model_validate(email)


@router.post(
    "/match-preview",
    response_model=MatcherPreviewResponse,
    summary="Preview matcher hits: top N recent mails, or one mail by mail_id",
)
async def matcher_preview(
    payload: MatcherPreviewRequest,
    db: Session = Depends(get_db),
) -> MatcherPreviewResponse:
    """
    With ``mail_id``: load that cached row and set ``matched`` (``items`` includes that mail).
    Without ``mail_id``: scan newest mails in ``lookback_days`` until ``limit`` matches (max 10).
    """
    subject_rx = _compile_optional_regex(payload.subject_match_regex, "subject")
    sender_rx = _compile_optional_regex(payload.sender_match_regex, "sender")
    body_rx = _compile_optional_regex(payload.body_match_regex, "body")
    has_matchers = subject_rx is not None or sender_rx is not None or body_rx is not None

    mail_id = (payload.mail_id or "").strip()
    if mail_id:
        email = db.execute(select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)).scalar_one_or_none()
        if email is None:
            raise HTTPException(status_code=404, detail="Email not found")
        content = FetchedEmailContentRead.model_validate(email)
        if not has_matchers:
            return MatcherPreviewResponse(
                items=[],
                scanned=1,
                mail_id=mail_id,
                matched=None,
                tested_mail=content,
            )
        ok = _all_match(subject_rx=subject_rx, sender_rx=sender_rx, body_rx=body_rx, email=email)
        return MatcherPreviewResponse(
            items=[_matcher_preview_item(email)],
            scanned=1,
            mail_id=mail_id,
            matched=ok,
            tested_mail=content,
        )

    limit = int(payload.limit or 0)
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if limit > 10:
        raise HTTPException(status_code=400, detail="limit must be <= 10")

    lookback_days = int(payload.lookback_days or 0)
    if lookback_days < 1:
        raise HTTPException(status_code=400, detail="lookback_days must be >= 1")
    if lookback_days > 3650:
        raise HTTPException(status_code=400, detail="lookback_days is too large")

    if not has_matchers:
        return MatcherPreviewResponse(items=[], scanned=0, mail_id=None, matched=None)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    min_ms = now_ms - (lookback_days * 24 * 60 * 60 * 1000)

    items: list[MatcherPreviewItemRead] = []
    scanned = 0

    batch_size = 100
    max_scanned = 2000
    offset = 0

    while len(items) < limit and scanned < max_scanned:
        stmt = (
            select(FetchedEmail)
            .where(FetchedEmail.internal_date_ms >= min_ms)
            .order_by(FetchedEmail.internal_date_ms.desc(), FetchedEmail.id.desc())
            .offset(offset)
            .limit(batch_size)
        )
        batch = list(db.scalars(stmt).all())
        if not batch:
            break

        for email in batch:
            scanned += 1
            if _all_match(subject_rx=subject_rx, sender_rx=sender_rx, body_rx=body_rx, email=email):
                items.append(_matcher_preview_item(email))
                if len(items) >= limit:
                    break

            if scanned >= max_scanned:
                break

        offset += batch_size

    return MatcherPreviewResponse(items=items, scanned=scanned, mail_id=None, matched=None)


@router.post(
    "/extract-regex-preview",
    response_model=ExtractRegexPreviewResponse,
    summary="Extract-regex preview: match spans for one cached mail",
)
async def extract_regex_preview(
    payload: ExtractRegexPreviewRequest,
    db: Session = Depends(get_db),
) -> ExtractRegexPreviewResponse:
    """Return first-match spans per field for highlighting (regex evaluated server-side only)."""
    mail_id = (payload.mail_id or "").strip()
    if not mail_id:
        raise HTTPException(status_code=400, detail="mail_id is required")
    email = db.execute(select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)).scalar_one_or_none()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    body_haystack = (email.body_text or "") or (email.snippet or "")
    subject_raw = regex_field_preview(payload.subject_extract_regex, email.subject or "")
    body_raw = regex_field_preview(payload.body_extract_regex, body_haystack)
    snippet_raw = regex_field_preview(payload.snippet_extract_regex, email.snippet or "")

    return ExtractRegexPreviewResponse(
        mail_id=mail_id,
        subject=RegexFieldPreviewRead.model_validate(subject_raw),
        body=RegexFieldPreviewRead.model_validate(body_raw),
        snippet=RegexFieldPreviewRead.model_validate(snippet_raw),
    )


@router.get(
    "/{mail_id}",
    response_model=FetchedEmailWithEnrichmentResponse,
    summary="Get cached email by provider message id",
)
async def get_email_by_mail_id(
    mail_id: str = Path(
        ...,
        min_length=1,
        description=(
            "Provider message id — **must** match ``fetched_emails.mail_id`` "
            "(e.g. Gmail message id; same as ``transactions.mail_id``). "
            "Not the internal numeric ``fetched_emails.id``."
        ),
    ),
    db: Session = Depends(get_db),
) -> FetchedEmailWithEnrichmentResponse:
    """Return one cached email row and its enrichment (if any), keyed by ``mail_id``."""
    email = db.execute(select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)).scalar_one_or_none()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    enrichment = db.get(FetchedEmailEnrichment, email.id)
    base = FetchedEmailRead.model_validate(email)
    return FetchedEmailWithEnrichmentResponse(
        **base.model_dump(),
        enrichment=_enrichment_detail(db, enrichment) if enrichment else None,
    )
