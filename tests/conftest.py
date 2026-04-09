"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import os

# Before any ``backend.config`` import: avoid background scheduled mail ingest during API tests.
os.environ["API_SCHEDULED_INGEST_ENABLED"] = "false"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base

# Import all ORM models so Base.metadata knows about every table.
from backend.app.models.account import Account  # noqa: F401
from backend.app.models.classification import Classification
from backend.app.models.fetched_email import FetchedEmail  # noqa: F401
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment  # noqa: F401
from backend.app.models.mail_account import MailAccount  # noqa: F401
from backend.app.models.app_config import AppConfig  # noqa: F401
from backend.app.models.parser import Parser
from backend.app.models.transaction import Transaction  # noqa: F401
from backend.app.models.unparsed_message import UnparsedMessage  # noqa: F401
from backend.ingestion.persistence import (
    CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD,
    CONFIG_KEY_APP_MAIL_GMAIL_LABELS,
    CONFIG_KEY_APP_MAIL_INITIAL_LOOKBACK_DAYS,
    CONFIG_KEY_APP_MAIL_POLL_SECONDS,
    upsert_config_value,
)


@pytest.fixture()
def db() -> Session:
    """Yield an in-memory SQLite session with all tables created."""
    # StaticPool: one shared in-memory DB for all connections (TestClient uses another thread).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    # Seed required runtime config (mirrors the migration defaults).
    upsert_config_value(session, CONFIG_KEY_APP_MAIL_GMAIL_LABELS, "Finance")
    upsert_config_value(session, CONFIG_KEY_APP_MAIL_POLL_SECONDS, "300")
    upsert_config_value(session, CONFIG_KEY_APP_MAIL_INITIAL_LOOKBACK_DAYS, "30")
    upsert_config_value(session, CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD, "50")
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ── Seed helpers ──────────────────────────────────────────────────────────────

def seed_classification(
    db: Session,
    *,
    name: str = "Test rule",
    message_type: str = "TRANSACTION_ALERT",
    priority: int = 10,
    sender_match_regex: str | None = None,
    subject_match_regex: str | None = None,
    body_match_regex: str | None = None,
    body_extract_regex: str | None = None,
    subject_extract_regex: str | None = None,
    snippet_extract_regex: str | None = None,
) -> Classification:
    from backend.app.models.classification import MessageType
    row = Classification(
        name=name,
        message_type=MessageType(message_type),
        priority=priority,
        sender_match_regex=sender_match_regex,
        subject_match_regex=subject_match_regex,
        body_match_regex=body_match_regex,
        body_extract_regex=body_extract_regex,
        subject_extract_regex=subject_extract_regex,
        snippet_extract_regex=snippet_extract_regex,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def seed_parser(
    db: Session,
    *,
    name: str = "Test parser",
    label: str = "TEST",
    priority: int = 10,
    sender_match_regex: str | None = None,
    subject_match_regex: str | None = None,
    body_match_regex: str | None = None,
    body_extract_regex: str | None = None,
    subject_extract_regex: str | None = None,
    snippet_extract_regex: str | None = None,
    provider: str | None = None,
    account_type: str | None = None,
    txn_date_fmt: str | None = None,
    txn_time_fmt: str | None = None,
    default_account_id: str | None = None,
    default_category: str | None = None,
) -> Parser:
    row = Parser(
        name=name,
        label=label,
        priority=priority,
        sender_match_regex=sender_match_regex,
        subject_match_regex=subject_match_regex,
        body_match_regex=body_match_regex,
        body_extract_regex=body_extract_regex,
        subject_extract_regex=subject_extract_regex,
        snippet_extract_regex=snippet_extract_regex,
        provider=provider,
        account_type=account_type,
        txn_date_fmt=txn_date_fmt,
        txn_time_fmt=txn_time_fmt,
        default_account_id=default_account_id,
        default_category=default_category,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row
