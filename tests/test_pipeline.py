"""Integration tests for the ingest pipeline (_process_emails)."""

from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.transaction import Transaction
from backend.app.models.unparsed_message import UnparsedMessage
from backend.ingestion.extraction import EmailContent
from backend.ingestion.pipeline import _process_emails
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


def _email(
    msg_id: str = "msg1",
    sender: str = "alerts@hdfcbank.com",
    subject: str = "HDFC Alert",
    body: str = "A/c XX1234 debited INR 500.00",
    ts_ms: int = _TS_MS,
) -> EmailContent:
    return EmailContent(
        gmail_message_id=msg_id,
        thread_id="t1",
        subject=subject,
        sender=sender,
        snippet=body[:80],
        internal_date_ms=ts_ms,
        body_text=body,
    )


def _seed_alert_setup(db: Session, *, provider: str = "HDFC") -> None:
    """Insert a TRANSACTION_ALERT classification and a matching HDFC parser."""
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(db, sender_match_regex=r"hdfcbank",
                body_extract_regex=_DEBIT_REGEX, provider=provider)


# ── Happy path ────────────────────────────────────────────────────────────────

def test_email_parsed_into_transaction(db: Session) -> None:
    _seed_alert_setup(db)
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
    assert txn.gmail_message_id == "msg1"


def test_email_stored_in_fetched_emails(db: Session) -> None:
    _seed_alert_setup(db)
    _process_emails([_email()], db)

    row = db.get(FetchedEmail, "msg1")
    assert row is not None
    assert row.sender == "alerts@hdfcbank.com"
    assert "debited" in row.body_text


def test_fetched_email_classification_is_set(db: Session) -> None:
    _seed_alert_setup(db)
    _process_emails([_email()], db)

    row = db.get(FetchedEmail, "msg1")
    assert row.classification == "TRANSACTION_ALERT"


# ── SINK ──────────────────────────────────────────────────────────────────────

def test_sink_message_is_skipped(db: Session) -> None:
    seed_classification(db, message_type="SINK", subject_match_regex=r"(?i)newsletter")
    email = _email(subject="Monthly Newsletter", body="Unsubscribe here")
    stats = _process_emails([email], db)

    assert stats["skipped"] == 1
    assert stats["parsed"] == 0
    assert db.query(Transaction).count() == 0
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


def test_statement_classification_goes_to_unparsed(db: Session) -> None:
    seed_classification(db, message_type="STATEMENT", subject_match_regex=r"(?i)statement")
    email = _email(subject="Your March 2024 statement")
    stats = _process_emails([email], db)

    assert stats["unparsed"] == 1
    assert db.query(Transaction).count() == 0


# ── Parse failure ─────────────────────────────────────────────────────────────

def test_parse_failure_goes_to_unparsed(db: Session) -> None:
    # Classification matches but body doesn't match parser regex
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    seed_parser(db, sender_match_regex=r"hdfcbank",
                body_extract_regex=r"PATTERN THAT NEVER MATCHES", provider="HDFC")

    stats = _process_emails([_email()], db)
    assert stats["unparsed"] == 1
    assert db.query(UnparsedMessage).first().reason == "no_regex_match"


# ── Low confidence ────────────────────────────────────────────────────────────

def test_low_confidence_goes_to_unparsed(db: Session, monkeypatch) -> None:
    # Force confidence threshold to 100 so any parse fails the check
    monkeypatch.setattr("backend.ingestion.pipeline.settings.confidence_threshold", 100)
    _seed_alert_setup(db)
    stats = _process_emails([_email()], db)

    assert stats["unparsed"] == 1
    assert db.query(Transaction).count() == 0
    row = db.query(UnparsedMessage).first()
    assert "low_confidence" in row.reason


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


# ── store_emails=False ────────────────────────────────────────────────────────

def test_store_emails_false_does_not_write_fetched_email(db: Session) -> None:
    _seed_alert_setup(db)
    _process_emails([_email()], db, store_emails=False)

    assert db.query(FetchedEmail).count() == 0
    assert db.query(Transaction).count() == 1


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
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"hdfcbank")
    stats1 = _process_emails([_email()], db)
    assert stats1["unparsed"] == 1
    assert db.query(UnparsedMessage).count() == 1

    # Add a parser and reprocess
    seed_parser(db, sender_match_regex=r"hdfcbank",
                body_extract_regex=_DEBIT_REGEX, provider="HDFC")
    stats2 = _process_emails([_email()], db, store_emails=False)
    assert stats2["parsed"] == 1
    assert db.query(UnparsedMessage).count() == 0
