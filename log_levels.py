"""Custom logging levels used across CLI and database setup."""

from __future__ import annotations

import logging

# Finer than DEBUG; used to enable SQLAlchemy engine ``echo`` only at this level.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def parse_log_level(name: str) -> int:
    """Map setting string to a ``logging`` level int (supports ``TRACE``)."""
    key = (name or "INFO").strip().upper()
    if key == "TRACE":
        return TRACE
    return getattr(logging, key, logging.INFO)


def sqlalchemy_echo_from_log_level(name: str) -> bool:
    """SQL ``echo`` only when explicitly tracing (not for ``DEBUG``)."""
    return (name or "").strip().upper() == "TRACE"
