"""Cached email bodies + classifier/parser enrichment (read-only).

Lookup is always by **provider message id** (``FetchedEmail.mail_id``), not by the internal
surrogate ``FetchedEmail.id`` (the response includes ``id`` at the top level for that row).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.classification import Classification
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.parser import Parser
from backend.app.schemas import (
    FetchedEmailEnrichmentDetailRead,
    FetchedEmailRead,
    FetchedEmailWithEnrichmentResponse,
)
from backend.database import get_db

router = APIRouter()


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
        created_at=enrichment.created_at,
        updated_at=enrichment.updated_at,
        classification_name=c_name,
        parser_name=p_name,
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
