"""Integration tests for the ingest pipeline (_process_emails)."""

import argparse
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.transaction import Transaction
from backend.app.models.unparsed_message import UnparsedMessage
from backend.ingestion.extraction import EmailContent
from backend.ingestion.classifier import CLASSIFICATION_NO_MATCH_REASON
from backend.ingestion.pipeline import (
    _ingest_args_for_poll_tick,
    _process_emails,
    incremental_mail_ingest_tick_args,
)
from tests.conftest import seed_classification, seed_parser

_TS_MS = 1_709_251_200_000  # 2024-03-01 00:00:00 UTC

# Regex that parses a simple debit alert body
_DEBIT_REGEX = (
    r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
    r"(?:.*?ref\s+(?P<txn_id>\w+))?"
)
_CREDIT_REGEX = (
    r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_iscredit>credited)\s+INR\s+(?P<amount>[\d,.]+)"
)


def _fetched_by_mail_id(db: Session, mail_id: str) -> Optional[FetchedEmail]:
    return db.execute(select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)).scalar_one_or_none()


def _email(
    msg_id: str = "msg1",
    sender: str = "alerts@hdfcbank.com",
    subject: str = "HDFC Alert",
    body: str = "A/c XX1234 debited INR 500.00",
    ts_ms: int = _TS_MS,
) -> EmailContent:
    return EmailContent(
        mail_id=msg_id,
        thread_id="t1",
        subject=subject,
        sender=sender,
        snippet=body[:80],
        internal_date_ms=ts_ms,
        body_text=body,
    )


def _seed_alert_setup(db: Session, *, provider: str = "HDFC"):
    """Insert a TRANSACTION_ALERT classification and a matching HDFC parser."""
    classification = seed_classification(
        db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank"
    )
    parser = seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        body_extract_regex=_DEBIT_REGEX,
        provider=provider,
    )
    return classification, parser


def _enrichment(db: Session, fetched_email_id: int) -> Optional[FetchedEmailEnrichment]:
    return db.get(FetchedEmailEnrichment, fetched_email_id)


# ── Happy path ────────────────────────────────────────────────────────────────

def test_email_parsed_into_transaction(db: Session) -> None:
    classification, parser = _seed_alert_setup(db)
    stats = _process_emails([_email()], db)

    assert stats["parsed"] == 1
    assert stats["fetched"] == 1
    assert stats["unparsed"] == 0

    txn = db.query(Transaction).first()
    assert txn is not None
    assert txn.amount_parsed == 500.0
    assert txn.direction == "DEBIT"
    assert txn.account_id == "XX1234"
    assert txn.provider == "HDFC"
    assert txn.mail_id == "msg1"

    fetched = _fetched_by_mail_id(db, "msg1")
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id == parser.id


def test_email_stored_in_fetched_emails(db: Session) -> None:
    _seed_alert_setup(db)
    _process_emails([_email()], db)

    row = _fetched_by_mail_id(db, "msg1")
    assert row is not None
    assert row.sender == "alerts@hdfcbank.com"
    assert "debited" in row.body_text


def test_fetched_email_raw_row_is_not_updated_on_repeat(db: Session) -> None:
    """Same mail_id: second ingest must not overwrite body_text."""
    seed_classification(db, message_type="SINK", subject_match_regex=r".*")
    _process_emails([_email(body="first body content")], db)
    _process_emails([_email(body="second body replaced")], db)
    row = _fetched_by_mail_id(db, "msg1")
    assert row is not None
    assert "first body content" in row.body_text
    assert "second body" not in row.body_text


def test_fetched_email_classification_is_set(db: Session) -> None:
    classification, _parser = _seed_alert_setup(db)
    _process_emails([_email()], db)

    fetched = _fetched_by_mail_id(db, "msg1")
    assert fetched is not None
    row = _enrichment(db, fetched.id)
    assert row is not None
    assert row.classification == "TRANSACTION_ALERT"
    assert row.classification_id == classification.id
    assert row.classification_reason == "Test rule"
    assert row.processing_time_ms is not None
    assert row.processing_time_ms >= 0


# ── SINK ──────────────────────────────────────────────────────────────────────

def test_sink_message_is_skipped(db: Session) -> None:
    classification = seed_classification(
        db, message_type="SINK", subject_match_regex=r"(?i)newsletter"
    )
    email = _email(subject="Monthly Newsletter", body="Unsubscribe here")
    stats = _process_emails([email], db)

    assert stats["skipped"] == 1
    assert stats["parsed"] == 0
    assert db.query(Transaction).count() == 0
    assert db.query(UnparsedMessage).count() == 0

    fetched = _fetched_by_mail_id(db, email.mail_id)
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification == "SINK"
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"


def test_sink_removes_existing_unparsed_row(db: Session) -> None:
    """Re-classify as SINK should clear a stale unparsed queue row."""
    fe = FetchedEmail(
        mail_id="msg1",
        thread_id="t1",
        subject="Monthly Newsletter",
        sender="news@example.com",
        snippet="",
        internal_date_ms=_TS_MS,
        body_text="Unsubscribe here",
    )
    db.add(fe)
    db.flush()
    db.add(
        UnparsedMessage(
            fetched_email_id=fe.id,
            reason="classification:OTHER",
            classification_id=None,
            parser_id=None,
        )
    )
    db.commit()

    seed_classification(db, message_type="SINK", subject_match_regex=r"(?i)newsletter")
    email = _email(subject="Monthly Newsletter", body="Unsubscribe here")
    stats = _process_emails([email], db)

    assert stats["skipped"] == 1
    assert db.query(UnparsedMessage).count() == 0


# ── OTHER / unclassified ──────────────────────────────────────────────────────

def test_other_classification_goes_to_unparsed(db: Session) -> None:
    # No classification rules → defaults to OTHER
    stats = _process_emails([_email(sender="friend@gmail.com", subject="Lunch?")], db)

    assert stats["unparsed"] == 1
    assert stats["parsed"] == 0

    row = db.query(UnparsedMessage).first()
    assert row is not None
    assert "OTHER" in row.reason

    fetched = _fetched_by_mail_id(db, _email().mail_id)
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification == "OTHER"
    assert enr.classification_id is None
    assert enr.classification_reason == CLASSIFICATION_NO_MATCH_REASON
    assert enr.parser_id is None


def test_statement_classification_goes_to_unparsed(db: Session) -> None:
    classification = seed_classification(
        db, message_type="STATEMENT", subject_match_regex=r"(?i)statement"
    )
    email = _email(subject="Your March 2024 statement")
    stats = _process_emails([email], db)

    assert stats["unparsed"] == 1
    assert db.query(Transaction).count() == 0

    fetched = _fetched_by_mail_id(db, email.mail_id)
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id is None


def test_investment_notice_classification_goes_to_unparsed(db: Session) -> None:
    classification = seed_classification(
        db, message_type="INVESTMENT_NOTICE", subject_match_regex=r"(?i)SIP|mutual fund"
    )
    email = _email(subject="Your SIP for March")
    stats = _process_emails([email], db)

    assert stats["unparsed"] == 1
    assert db.query(Transaction).count() == 0
    row = db.query(UnparsedMessage).first()
    assert row is not None
    assert row.reason == "classification:INVESTMENT_NOTICE"

    fetched = _fetched_by_mail_id(db, email.mail_id)
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id is None


# ── Parse failure ─────────────────────────────────────────────────────────────

def test_parse_failure_goes_to_unparsed(db: Session) -> None:
    # Classification matches but body doesn't match parser regex
    classification = seed_classification(
        db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank"
    )
    parser = seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        body_extract_regex=r"PATTERN THAT NEVER MATCHES",
        provider="HDFC",
    )

    stats = _process_emails([_email()], db)
    assert stats["unparsed"] == 1
    assert db.query(UnparsedMessage).first().reason == "no_regex_match"

    fetched = _fetched_by_mail_id(db, "msg1")
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id == parser.id


# ── Low confidence ────────────────────────────────────────────────────────────

def test_low_confidence_goes_to_unparsed(db: Session, monkeypatch) -> None:
    # Force confidence threshold to 100 so any parse fails the check
    from backend.ingestion.persistence import (
        CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD,
        upsert_config_value,
    )

    upsert_config_value(db, CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD, "100")
    classification, parser = _seed_alert_setup(db)
    stats = _process_emails([_email()], db)

    assert stats["unparsed"] == 1
    assert db.query(Transaction).count() == 0
    row = db.query(UnparsedMessage).first()
    assert "low_confidence" in row.reason

    fetched = _fetched_by_mail_id(db, "msg1")
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id == parser.id


# ── Duplicate deduplication ───────────────────────────────────────────────────

def test_duplicate_transaction_is_skipped(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(
        db, sender_match_regex=r"hdfcbank", provider="HDFC",
        body_extract_regex=(
            r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
            r".*?ref\s+(?P<txn_id>\w+)"
        ),
    )
    body = "A/c XX1234 debited INR 500.00 ref TXN999"
    email1 = _email(msg_id="msg1", body=body)
    email2 = _email(msg_id="msg2", body=body)

    stats = _process_emails([email1, email2], db)

    assert stats["parsed"] == 1
    assert stats["duplicate"] == 1
    assert db.query(Transaction).count() == 1


def test_reprocessing_same_mail_replaces_transaction(db: Session) -> None:
    """Re-ingesting the same message_id deletes prior ledger rows for that mail before insert."""
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        provider="HDFC",
        body_extract_regex=(
            r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
            r".*?ref\s+(?P<txn_id>\w+)"
        ),
    )
    body = "A/c XX1234 debited INR 500.00 ref TXN999"
    email = _email(msg_id="same-msg", body=body)

    stats1 = _process_emails([email], db)
    assert stats1["parsed"] == 1
    assert db.query(Transaction).filter(Transaction.mail_id == "same-msg").count() == 1

    stats2 = _process_emails([email], db)
    assert stats2["parsed"] == 1
    assert stats2["duplicate"] == 0
    assert db.query(Transaction).count() == 1
    row = db.query(Transaction).filter(Transaction.mail_id == "same-msg").one()
    assert row.amount_parsed == 500.0


# ── Re-process: enrichment always refreshed ───────────────────────────────────

def test_reprocess_from_db_row_updates_enrichment(db: Session) -> None:
    """Simulate ``--offline``: existing ``fetched_emails`` row; enrichment is rewritten."""
    fe = FetchedEmail(
        mail_id="msg1",
        thread_id="t1",
        subject="HDFC Alert",
        sender="alerts@hdfcbank.com",
        snippet="debited",
        internal_date_ms=_TS_MS,
        body_text="A/c XX1234 debited INR 500.00",
    )
    db.add(fe)
    db.flush()
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe.id,
            classification="OTHER",
            classification_id=None,
            classification_reason=None,
            parser_id=None,
        )
    )
    db.commit()

    classification, parser = _seed_alert_setup(db)
    email = EmailContent(
        mail_id=fe.mail_id,
        thread_id=fe.thread_id or "",
        subject=fe.subject or "",
        sender=fe.sender or "",
        snippet=fe.snippet or "",
        internal_date_ms=fe.internal_date_ms,
        body_text=fe.body_text or "",
        fetched_email_id=fe.id,
    )
    stats = _process_emails([email], db)

    assert stats["parsed"] == 1
    enr = _enrichment(db, fe.id)
    assert enr is not None
    assert enr.classification == "TRANSACTION_ALERT"
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id == parser.id


def test_ingest_one_from_fetched_by_mail_id(db: Session) -> None:
    """New CLI feature: re-process one cached email by mail_id."""
    from backend.ingestion.pipeline import _ingest_one_from_fetched

    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(
        db,
        sender_match_regex=r"hdfcbank",
        provider="HDFC",
        body_extract_regex=(
            r"A/c\s+(?P<account_id>\w+)\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d,.]+)"
            r".*?ref\s+(?P<txn_id>\w+)"
        ),
    )

    # First, ensure a fetched_emails row exists (insert-only cache).
    email = _email(msg_id="only-mid", body="A/c XX1234 debited INR 500.00 ref TXN888")
    _process_emails([email], db)

    # Then re-process only that mail_id from the cached row.
    _ingest_one_from_fetched(db, "only-mid")
    assert db.query(Transaction).filter(Transaction.mail_id == "only-mid").count() == 1


# ── Multiple emails in one batch ──────────────────────────────────────────────

def test_multiple_emails_are_all_processed(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    # Separate parsers with body_match_regex so each only claims its own email type
    seed_parser(db, sender_match_regex=r"hdfcbank", body_match_regex=r"debited",
                body_extract_regex=_DEBIT_REGEX, provider="HDFC", priority=10)
    seed_parser(db, sender_match_regex=r"hdfcbank", body_match_regex=r"credited",
                body_extract_regex=_CREDIT_REGEX, provider="HDFC", priority=5)

    emails = [
        _email(msg_id="d1", body="A/c XX1111 debited INR 100.00"),
        _email(msg_id="c1", body="A/c XX2222 credited INR 200.00"),
        _email(msg_id="d2", body="A/c XX3333 debited INR 300.00"),
    ]
    stats = _process_emails(emails, db)

    assert stats["fetched"] == 3
    assert stats["parsed"] == 3
    assert db.query(Transaction).count() == 3


# ── Re-process: successful parse removes from unparsed queue ──────────────────

def test_successful_reparse_removes_from_unparsed(db: Session) -> None:
    # First pass: no parser → goes to unparsed
    classification = seed_classification(
        db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank"
    )
    stats1 = _process_emails([_email()], db)
    assert stats1["unparsed"] == 1
    assert db.query(UnparsedMessage).count() == 1

    # Add a parser and reprocess
    parser = seed_parser(
        db, sender_match_regex=r"hdfcbank", body_extract_regex=_DEBIT_REGEX, provider="HDFC"
    )
    stats2 = _process_emails([_email()], db)
    assert stats2["parsed"] == 1
    assert db.query(UnparsedMessage).count() == 0

    fetched = _fetched_by_mail_id(db, "msg1")
    assert fetched is not None
    enr = _enrichment(db, fetched.id)
    assert enr is not None
    assert enr.classification_id == classification.id
    assert enr.classification_reason == "Test rule"
    assert enr.parser_id == parser.id


def test_incremental_mail_ingest_tick_args_matches_poll_default() -> None:
    base = argparse.Namespace(mail=True, unparsed=False, offline=False)
    assert (
        incremental_mail_ingest_tick_args().__dict__
        == _ingest_args_for_poll_tick(base).__dict__
    )
