"""Shared database initialisation for ingestion and API layers.

``engine`` and ``SessionLocal`` are the two objects imported by every module
that needs DB access.  ``Base`` is the SQLAlchemy declarative base that all
ORM models inherit from.

Usage::

    from backend.database import SessionLocal

    with SessionLocal() as session:
        ...
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings
from backend.log_levels import sqlalchemy_echo_from_log_level

engine = create_engine(
    settings.database_url,
    # SQLite-specific: enable WAL mode for better concurrency
    connect_args={"check_same_thread": False},
    echo=sqlalchemy_echo_from_log_level(settings.log_level),
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def get_db():
    """FastAPI dependency that yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
