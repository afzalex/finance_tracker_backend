"""Cached email bodies + classifier/parser enrichment (read-only).

Lookup is always by **provider message id** (``FetchedEmail.mail_id``), not by the internal
surrogate ``FetchedEmail.id`` (the response includes ``id`` at the top level for that row).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import subprocess
import sys
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.classification import Classification
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.parser import Parser
from backend.app.models.unparsed_message import UnparsedMessage
from backend.app.schemas import (
    FetchedEmailEnrichmentDetailRead,
    FetchedEmailRead,
    FetchedEmailWithEnrichmentResponse,
    UnparsedEmailListItem,
)
from backend.database import get_db
from backend.ingestion.pipeline import reprocess_all_from_fetched, reprocess_one_from_fetched

router = APIRouter()
logger = logging.getLogger(__name__)

_REPROCESS_JOBS: dict[str, dict] = {}
_REPROCESS_PROCS: dict[str, subprocess.Popen] = {}

_ACTIVE_STATUSES = {"queued", "running"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_reprocess_job_id() -> str | None:
    # Keep it simple: single in-memory coordinator per process.
    # This is enough for local dev and single-worker deployments.
    for job_id, job in _REPROCESS_JOBS.items():
        if job.get("status") in _ACTIVE_STATUSES:
            return job_id
    return None


def _monitor_reprocess_proc(job_id: str) -> None:
    proc = _REPROCESS_PROCS.get(job_id)
    if proc is None:
        return
    rc = proc.wait()
    if rc == 0:
        _REPROCESS_JOBS[job_id] = {
            "status": "completed",
            "started_at": _REPROCESS_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
        }
        logger.info("emails.reprocess_all job completed", extra={"job_id": job_id})
    else:
        _REPROCESS_JOBS[job_id] = {
            "status": "failed",
            "started_at": _REPROCESS_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "error": f"exit_code={rc}",
        }
        logger.error("emails.reprocess_all job failed", extra={"job_id": job_id, "exit_code": rc})
    _REPROCESS_PROCS.pop(job_id, None)


@router.get(
    "/reprocess/{job_id}",
    summary="Get status for a bulk offline reprocess job",
)
async def get_reprocess_job(job_id: str = Path(..., min_length=1)) -> dict:
    job = _REPROCESS_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


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
    "/unparsed",
    response_model=list[UnparsedEmailListItem],
    summary="List emails in the unparsed queue",
)
async def list_unparsed_emails(db: Session = Depends(get_db)) -> list[UnparsedEmailListItem]:
    """Return unparsed queue rows with ``mail_id`` and subject/snippet from ``fetched_emails`` (newest first)."""
    stmt = (
        select(UnparsedMessage, FetchedEmail)
        .join(FetchedEmail, UnparsedMessage.fetched_email_id == FetchedEmail.id)
        .order_by(UnparsedMessage.created_at.desc(), UnparsedMessage.id.desc())
    )
    rows = db.execute(stmt).all()
    out: list[UnparsedEmailListItem] = []
    for um, fe in rows:
        c_name, p_name = _rule_name(db, um.classification_id, um.parser_id)
        out.append(
            UnparsedEmailListItem(
                id=um.id,
                fetched_email_id=um.fetched_email_id,
                mail_id=fe.mail_id,
                subject=fe.subject,
                snippet=fe.snippet,
                reason=um.reason,
                classification_id=um.classification_id,
                parser_id=um.parser_id,
                classification_name=c_name,
                parser_name=p_name,
                created_at=um.created_at,
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


@router.post(
    "/reprocess",
    summary="Re-process all cached emails (offline)",
)
async def reprocess_all_emails_offline(
    wait: bool = Query(
        False,
        description=(
            "If true, run synchronously and return final stats (can take a long time). "
            "If false (default), start a background job and return immediately."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run classification + parsing for all cached emails (no Gmail fetch)."""
    if wait:
        logger.info("emails.reprocess_all sync requested")
        stats = reprocess_all_from_fetched(db)
        return {"stats": stats}

    active_job_id = _active_reprocess_job_id()
    if active_job_id is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A reprocess job is already running",
                "job_id": active_job_id,
            },
        )

    job_id = uuid4().hex
    _REPROCESS_JOBS[job_id] = {"status": "running", "started_at": _utc_now_iso()}
    logger.info("emails.reprocess_all queued", extra={"job_id": job_id})
    # Run in a separate OS process so the API stays responsive.
    # We delegate to the existing CLI offline ingest command.
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.cli", "ingest", "--offline"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    _REPROCESS_PROCS[job_id] = proc
    Thread(target=_monitor_reprocess_proc, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


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
