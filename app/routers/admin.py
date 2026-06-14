"""Admin-only operational endpoints (bulk jobs, maintenance)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
import logging
import subprocess
import sys
from threading import Event, Thread
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from backend.ingestion.gmail.auth import (
    GmailAuthError,
    SCOPES,
    persist_gmail_oauth_credentials,
)
from backend.database import get_db
from backend.ingestion.mail.errors import MailProviderAuthError
from backend.ingestion.pipeline import IngestCancelled, mail_force_ingest_args, reprocess_all_from_fetched, run_ingest
from backend.app.schemas.mail_ingest import (
    MailIngestCancelResponse,
    MailIngestConflictDetail,
    MailIngestJobRead,
    MailIngestStatusRead,
    MailIngestSyncResponse,
    MailIngestTriggerResponse,
    mail_ingest_job_read,
    mail_ingest_stats_from_dict,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_GMAIL_OAUTH_PENDING: dict[str, dict] = {}

_REPROCESS_JOBS: dict[str, dict] = {}
_REPROCESS_PROCS: dict[str, subprocess.Popen] = {}

_MAIL_INGEST_JOBS: dict[str, dict] = {}
_MAIL_INGEST_CANCEL: dict[str, Event] = {}

_ACTIVE_STATUSES = {"queued", "running", "cancelling"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_reprocess_job_id() -> str | None:
    for job_id, job in _REPROCESS_JOBS.items():
        if job.get("status") in _ACTIVE_STATUSES:
            return job_id
    return None


def _active_mail_ingest_job_id() -> str | None:
    for job_id, job in _MAIL_INGEST_JOBS.items():
        if job.get("status") in _ACTIVE_STATUSES:
            return job_id
    return None


def _active_mail_ingest_job() -> tuple[str, dict] | None:
    job_id = _active_mail_ingest_job_id()
    if job_id is None:
        return None
    return job_id, _MAIL_INGEST_JOBS[job_id]


def _mail_ingest_conflict(active_job_id: str, job: dict) -> HTTPException:
    detail = MailIngestConflictDetail(
        job_id=active_job_id,
        status=job["status"],
        lookback_days=job.get("lookback_days"),
        started_at=job.get("started_at"),
    )
    return HTTPException(status_code=409, detail=detail.model_dump())


def _run_mail_ingest_job(job_id: str, args) -> None:
    try:
        stats = run_ingest(args)
        _MAIL_INGEST_JOBS[job_id] = {
            "status": "completed",
            "started_at": _MAIL_INGEST_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "lookback_days": _MAIL_INGEST_JOBS.get(job_id, {}).get("lookback_days"),
            "max_messages": _MAIL_INGEST_JOBS.get(job_id, {}).get("max_messages"),
            "stats": stats,
        }
        logger.info("admin.mail.ingest completed", extra={"job_id": job_id})
    except IngestCancelled as exc:
        _MAIL_INGEST_JOBS[job_id] = {
            "status": "cancelled",
            "started_at": _MAIL_INGEST_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "lookback_days": _MAIL_INGEST_JOBS.get(job_id, {}).get("lookback_days"),
            "max_messages": _MAIL_INGEST_JOBS.get(job_id, {}).get("max_messages"),
            "stats": exc.stats,
        }
        logger.info("admin.mail.ingest cancelled", extra={"job_id": job_id})
    except MailProviderAuthError as exc:
        _MAIL_INGEST_JOBS[job_id] = {
            "status": "failed",
            "started_at": _MAIL_INGEST_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "lookback_days": _MAIL_INGEST_JOBS.get(job_id, {}).get("lookback_days"),
            "max_messages": _MAIL_INGEST_JOBS.get(job_id, {}).get("max_messages"),
            "error": str(exc),
        }
        logger.warning("admin.mail.ingest auth failed", extra={"job_id": job_id})
    except Exception as exc:  # noqa: BLE001
        _MAIL_INGEST_JOBS[job_id] = {
            "status": "failed",
            "started_at": _MAIL_INGEST_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "lookback_days": _MAIL_INGEST_JOBS.get(job_id, {}).get("lookback_days"),
            "max_messages": _MAIL_INGEST_JOBS.get(job_id, {}).get("max_messages"),
            "error": str(exc),
        }
        logger.exception("admin.mail.ingest failed", extra={"job_id": job_id})
    finally:
        _MAIL_INGEST_CANCEL.pop(job_id, None)


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
        logger.info("admin.emails.reprocess_all completed", extra={"job_id": job_id})
    else:
        _REPROCESS_JOBS[job_id] = {
            "status": "failed",
            "started_at": _REPROCESS_JOBS.get(job_id, {}).get("started_at"),
            "completed_at": _utc_now_iso(),
            "error": f"exit_code={rc}",
        }
        logger.error("admin.emails.reprocess_all failed", extra={"job_id": job_id, "exit_code": rc})
    _REPROCESS_PROCS.pop(job_id, None)


@router.get(
    "/emails/reprocess/{job_id}",
    summary="Get status for a bulk offline reprocess job",
)
async def get_reprocess_job(job_id: str = Path(..., min_length=1)) -> dict:
    job = _REPROCESS_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


@router.post(
    "/emails/reprocess",
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
    """Re-run classification + parsing for all cached emails (no remote mail fetch)."""
    if wait:
        logger.info("admin.emails.reprocess_all sync requested")
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
    logger.info("admin.emails.reprocess_all queued", extra={"job_id": job_id})
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
    "/mail/ingest/status",
    response_model=MailIngestStatusRead,
    summary="Current mail ingest job status",
)
async def get_mail_ingest_status() -> MailIngestStatusRead:
    """Return whether mail ingestion is in progress and the active job snapshot, if any."""
    active = _active_mail_ingest_job()
    if active is None:
        return MailIngestStatusRead(in_progress=False, job=None)
    job_id, job = active
    return MailIngestStatusRead(
        in_progress=True,
        job=mail_ingest_job_read(job_id, job),
    )


@router.get(
    "/mail/ingest/{job_id}",
    response_model=MailIngestJobRead,
    summary="Get status for a mail ingest job",
)
async def get_mail_ingest_job(job_id: str = Path(..., min_length=1)) -> MailIngestJobRead:
    job = _MAIL_INGEST_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return mail_ingest_job_read(job_id, job)


@router.post(
    "/mail/ingest/{job_id}/cancel",
    response_model=MailIngestCancelResponse,
    summary="Cancel a running mail ingest job",
)
async def cancel_mail_ingest_job(job_id: str = Path(..., min_length=1)) -> MailIngestCancelResponse:
    """Request cooperative cancellation; the job stops after the current message finishes."""
    job = _MAIL_INGEST_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    status = job.get("status")
    if status not in {"running", "cancelling"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not running (status={status!r})",
        )
    cancel_ev = _MAIL_INGEST_CANCEL.get(job_id)
    if cancel_ev is not None:
        cancel_ev.set()
    job["status"] = "cancelling"
    return MailIngestCancelResponse(job_id=job_id, status="cancelling")


@router.post(
    "/mail/ingest",
    response_model=MailIngestTriggerResponse | MailIngestSyncResponse,
    summary="Fetch and ingest mail from the last N days",
    responses={
        409: {
            "description": "Ingestion already in progress",
            "model": MailIngestConflictDetail,
        },
    },
)
async def trigger_mail_ingest(
    days: int = Query(
        ...,
        ge=1,
        le=3650,
        description=(
            "Re-fetch messages from the last N calendar days, ignoring the stored cursor "
            "(same as ``ingest --force`` with a custom lookback window)."
        ),
    ),
    max_messages: int | None = Query(
        None,
        ge=1,
        description="Optional cap on messages processed (newest first in the window).",
    ),
    wait: bool = Query(
        False,
        description=(
            "If true, run synchronously and return ingest stats (can take a long time). "
            "If false (default), start a background job and return immediately."
        ),
    ),
) -> MailIngestTriggerResponse | MailIngestSyncResponse:
    """Pull mail from the configured provider (Gmail today) and run the ingest pipeline."""
    active = _active_mail_ingest_job()
    if active is not None:
        raise _mail_ingest_conflict(active[0], active[1])

    args = mail_force_ingest_args(lookback_days=days, max_messages=max_messages)

    if wait:
        logger.info("admin.mail.ingest sync requested", extra={"lookback_days": days})
        try:
            stats = await asyncio.to_thread(run_ingest, args)
        except MailProviderAuthError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return MailIngestSyncResponse(
            lookback_days=days,
            stats=mail_ingest_stats_from_dict(stats),
        )

    job_id = uuid4().hex
    cancel_event = Event()
    _MAIL_INGEST_CANCEL[job_id] = cancel_event
    args.cancel_event = cancel_event
    _MAIL_INGEST_JOBS[job_id] = {
        "status": "running",
        "started_at": _utc_now_iso(),
        "lookback_days": days,
        "max_messages": max_messages,
    }
    logger.info(
        "admin.mail.ingest queued",
        extra={"job_id": job_id, "lookback_days": days},
    )
    Thread(target=_run_mail_ingest_job, args=(job_id, args), daemon=True).start()
    return MailIngestTriggerResponse(
        job_id=job_id,
        status="running",
        lookback_days=days,
        max_messages=max_messages,
    )


@router.post(
    "/mail/gmail/token/start",
    summary="Start Gmail OAuth flow to store token in mail_accounts",
)
async def start_gmail_oauth_token_flow(
    request: Request,
    redirect_uri: str | None = Query(
        None,
        description=(
            "OAuth redirect URI registered in Google Cloud Console. "
            "If omitted, defaults to this backend's callback URL."
        ),
        min_length=8,
    ),
) -> dict:
    """Return an auth_url to open in a browser. Call the callback endpoint to finish and persist the token."""
    from backend.config import settings  # local import to keep module import lightweight

    credentials_file = settings.gmail_credentials_file
    if redirect_uri is None:
        redirect_uri = (
            str(request.base_url).rstrip("/")
            + "/api/v1/admin/mail/gmail/token/callback"
        )

    if not os.path.exists(credentials_file):
        raise HTTPException(status_code=409, detail=f"Missing credentials.json at {credentials_file!r}")

    flow = Flow.from_client_secrets_file(credentials_file, scopes=SCOPES, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # PKCE: google-auth-oauthlib generates a code_verifier internally.
    # We must persist it across requests (state -> verifier) for fetch_token().
    code_verifier = getattr(flow, "code_verifier", None)
    _GMAIL_OAUTH_PENDING[state] = {
        "redirect_uri": redirect_uri,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_verifier": code_verifier,
    }
    return {"auth_url": auth_url, "state": state}


@router.get(
    "/mail/gmail/token/callback",
    summary="Finish Gmail OAuth flow and store token in mail_accounts",
)
async def finish_gmail_oauth_token_flow(
    state: str = Query(..., min_length=10),
    code: str = Query(..., min_length=10),
    db: Session = Depends(get_db),
) -> dict:
    """Exchange the OAuth code for tokens and persist to ``mail_accounts``."""
    from backend.config import settings  # local import to keep module import lightweight

    pending = _GMAIL_OAUTH_PENDING.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="Unknown or expired OAuth state")

    credentials_file = settings.gmail_credentials_file
    redirect_uri = pending["redirect_uri"]
    code_verifier = pending.get("code_verifier")

    if not os.path.exists(credentials_file):
        raise HTTPException(status_code=409, detail=f"Missing credentials.json at {credentials_file!r}")

    flow = Flow.from_client_secrets_file(credentials_file, scopes=SCOPES, redirect_uri=redirect_uri, state=state)
    if code_verifier:
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code, code_verifier=code_verifier)
    else:
        flow.fetch_token(code=code)
    creds = flow.credentials
    try:
        row = persist_gmail_oauth_credentials(db, creds)
    except GmailAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "ok", "mail_account_id": row.id, "account_mail_id": row.account_mail_id}
