"""Background scheduled mail ingest while the API process is running.

Uses the same entry point and tick arguments as the CLI ``poll`` command
(``run_ingest`` + ``incremental_mail_ingest_tick_args``), on ``settings.poll_seconds``.
The concrete provider is configured in code (Gmail today; others may be added later).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from backend.config import settings
from backend.ingestion.mail.errors import MailProviderAuthError
from backend.ingestion.pipeline import incremental_mail_ingest_tick_args, run_ingest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fastapi import FastAPI


@asynccontextmanager
async def scheduled_ingest_lifespan(_app: FastAPI):
    if not settings.api_scheduled_ingest_enabled:
        yield
        return

    stop = asyncio.Event()
    interval_sec = max(1, int(settings.poll_seconds))

    async def _loop() -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(run_ingest, incremental_mail_ingest_tick_args())
            except MailProviderAuthError:
                logger.warning("Scheduled mail ingest skipped — mail provider not authenticated")
            except Exception:
                logger.exception("Scheduled mail ingest tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_loop(), name="scheduled_mail_ingest")
    yield
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
