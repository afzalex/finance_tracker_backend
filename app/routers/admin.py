"""Admin-only operational endpoints (bulk jobs, maintenance)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import subprocess
import sys
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.ingestion.pipeline import reprocess_all_from_fetched

router = APIRouter()
logger = logging.getLogger(__name__)

_REPROCESS_JOBS: dict[str, dict] = {}
_REPROCESS_PROCS: dict[str, subprocess.Popen] = {}

_ACTIVE_STATUSES = {"queued", "running"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_reprocess_job_id() -> str | None:
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
