"""Console logging for ``backend.*`` under uvicorn.

Uvicorn's default ``LOGGING_CONFIG`` only wires handlers to ``uvicorn`` loggers. The root
logger has no handler, and Python's ``lastResort`` handler is WARNING — so INFO from
``backend.ingestion`` (e.g. per-tick summaries) never appears unless we attach a handler
here. Child loggers still propagate so pytest ``caplog`` on the root logger works.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.log_levels import parse_log_level


def ensure_backend_stderr_logging() -> None:
    log = logging.getLogger("backend")
    if not log.handlers:
        h = logging.StreamHandler()
        # Same visual shape as uvicorn default logs: ``INFO:     message…``
        from uvicorn.logging import DefaultFormatter

        h.setFormatter(
            DefaultFormatter(
                fmt="%(levelprefix)s %(asctime)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                use_colors=None,
            )
        )
        log.addHandler(h)
    log.setLevel(parse_log_level(settings.log_level or "INFO"))
