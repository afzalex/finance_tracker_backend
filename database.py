"""Shared database initialisation for ingestion and API layers.

``engine`` and ``SessionLocal`` are the two objects imported by every module
that needs DB access.  ``Base`` is the SQLAlchemy declarative base that all
ORM models inherit from.

Usage::

    from backend.database import SessionLocal

    with SessionLocal() as session:
        ...
"""

from __future__ import annotations

import random
import time

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings
from backend.log_levels import sqlalchemy_echo_from_log_level

_SQLITE = settings.database_url.startswith("sqlite")

_SQLITE_CONNECT_ARGS = (
    {"check_same_thread": False, "timeout": 10.0} if _SQLITE else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_SQLITE_CONNECT_ARGS,
    echo=sqlalchemy_echo_from_log_level(settings.log_level),
    pool_pre_ping=True,
)

if _SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def commit_with_retry(
    db: Session,
    *,
    attempts: int = 12,
    base_delay: float = 0.05,
    max_delay: float = 1.5,
) -> None:
    """Commit with retries when SQLite reports ``database is locked`` / ``busy``."""
    last: OperationalError | None = None
    for attempt in range(attempts):
        try:
            db.commit()
            return
        except OperationalError as exc:
            last = exc
            db.rollback()
            raw = str(getattr(exc, "orig", exc))
            if "locked" not in raw.lower() and "busy" not in raw.lower():
                raise
            if attempt >= attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2**attempt) + random.uniform(0, base_delay))
            time.sleep(delay)
    assert last is not None
    raise last


def flush_with_retry(
    db: Session,
    *,
    attempts: int = 12,
    base_delay: float = 0.05,
    max_delay: float = 1.5,
) -> None:
    """Retry ``flush()`` on SQLite locked/busy without rolling back the session between tries."""
    last: OperationalError | None = None
    for attempt in range(attempts):
        try:
            db.flush()
            return
        except OperationalError as exc:
            last = exc
            raw = str(getattr(exc, "orig", exc))
            if "locked" not in raw.lower() and "busy" not in raw.lower():
                db.rollback()
                raise
            if attempt >= attempts - 1:
                db.rollback()
                raise
            delay = min(max_delay, base_delay * (2**attempt) + random.uniform(0, base_delay))
            time.sleep(delay)
    assert last is not None
    raise last


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
