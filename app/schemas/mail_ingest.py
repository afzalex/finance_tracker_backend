"""Admin mail ingest job status schemas."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MailIngestJobStatus = Literal[
    "running",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
]


class MailIngestStats(BaseModel):
    """One-line ingest counters (subset returned when a job finishes)."""

    fetched: int = 0
    parsed: int = 0
    unparsed: int = 0
    skipped: int = 0
    duplicate: int = 0


class MailIngestJobRead(BaseModel):
    """Background or synchronous mail ingest job snapshot."""

    job_id: str
    status: MailIngestJobStatus
    started_at: str
    lookback_days: int
    max_messages: int | None = None
    completed_at: str | None = None
    stats: MailIngestStats | None = None
    error: str | None = None


class MailIngestStatusRead(BaseModel):
    """Whether a mail ingest job is active and its latest snapshot."""

    in_progress: bool = Field(
        ...,
        description="True when status is ``running`` or ``cancelling``.",
    )
    job: MailIngestJobRead | None = None


class MailIngestTriggerResponse(BaseModel):
    """Response when a background mail ingest job is queued."""

    job_id: str
    status: MailIngestJobStatus
    lookback_days: int
    max_messages: int | None = None


class MailIngestSyncResponse(BaseModel):
    """Response when ``wait=true`` on mail ingest."""

    lookback_days: int
    stats: MailIngestStats | None = None


class MailIngestConflictDetail(BaseModel):
    """409 body when ingestion is already in progress."""

    message: str = "Ingestion already in progress"
    job_id: str
    status: MailIngestJobStatus
    lookback_days: int | None = None
    started_at: str | None = None


class MailIngestCancelResponse(BaseModel):
    """Acknowledgement after requesting job cancellation."""

    job_id: str
    status: MailIngestJobStatus


def mail_ingest_stats_from_dict(raw: dict | None) -> MailIngestStats | None:
    if not raw:
        return None
    return MailIngestStats(
        fetched=int(raw.get("fetched") or 0),
        parsed=int(raw.get("parsed") or 0),
        unparsed=int(raw.get("unparsed") or 0),
        skipped=int(raw.get("skipped") or 0),
        duplicate=int(raw.get("duplicate") or 0),
    )


def mail_ingest_job_read(job_id: str, job: dict[str, Any]) -> MailIngestJobRead:
    return MailIngestJobRead(
        job_id=job_id,
        status=job["status"],
        started_at=job["started_at"],
        lookback_days=int(job.get("lookback_days") or 0),
        max_messages=job.get("max_messages"),
        completed_at=job.get("completed_at"),
        stats=mail_ingest_stats_from_dict(job.get("stats")),
        error=job.get("error"),
    )
