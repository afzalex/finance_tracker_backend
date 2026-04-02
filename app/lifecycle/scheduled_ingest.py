"""Background scheduled mail ingest while the API process is running.

Uses the same entry point and tick arguments as the CLI ``poll`` command
(``run_ingest`` + ``incremental_mail_ingest_tick_args``), on the interval configured
in DB ``app_config`` (key ``app.mail.poll_seconds``).
The concrete provider is configured in code (Gmail today; others may be added later).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from backend.config import settings
from backend.database import SessionLocal
from backend.ingestion.mail.errors import MailProviderAuthError
from backend.ingestion.persistence import CONFIG_KEY_APP_MAIL_POLL_SECONDS, get_required_config_int
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
    try:
        with SessionLocal() as db:
            interval_sec = get_required_config_int(db, CONFIG_KEY_APP_MAIL_POLL_SECONDS, min_value=1)
    except ValueError as exc:
        logger.error(
            "Scheduled mail ingest disabled — missing/invalid app_config (%s). "
            "Set it via /api/v1/app-config.",
            exc,
        )
        yield
        return

    async def _loop() -> None:
        nonlocal interval_sec
        while not stop.is_set():
            try:
                await asyncio.to_thread(run_ingest, incremental_mail_ingest_tick_args())
            except MailProviderAuthError:
                logger.warning("Scheduled mail ingest skipped — mail provider not authenticated")
            except Exception:
                logger.exception("Scheduled mail ingest tick failed")
            try:
                wait_task = asyncio.create_task(stop.wait())
                try:
                    await asyncio.wait_for(wait_task, timeout=interval_sec)
                finally:
                    wait_task.cancel()
            except asyncio.TimeoutError:
                pass
            try:
                with SessionLocal() as db:
                    interval_sec = get_required_config_int(db, CONFIG_KEY_APP_MAIL_POLL_SECONDS, min_value=1)
            except ValueError as exc:
                logger.error(
                    "Scheduled mail ingest disabled — missing/invalid app_config (%s). "
                    "Set it via /api/v1/app-config.",
                    exc,
                )
                stop.set()
                return

    task = asyncio.create_task(_loop(), name="scheduled_mail_ingest")
    yield
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
