"""Tests for MessageClassifier — DB-driven email classification."""

import pytest
from sqlalchemy.orm import Session

from backend.ingestion.classifier import ClassificationResult, MessageClassifier
from tests.conftest import seed_classification


def _classify(db: Session, sender: str = "", subject: str = "", body: str = "", snippet: str = "") -> ClassificationResult:
    c = MessageClassifier(db)
    c.load_rules()
    return c.classify(sender, subject, body, snippet)


# ── No rules → OTHER ──────────────────────────────────────────────────────────

def test_no_rules_returns_other(db: Session) -> None:
    result = _classify(db, sender="x@y.com", subject="Hello")
    assert result.message_type == "OTHER"
    assert result.classification_id is None


# ── Sender match ──────────────────────────────────────────────────────────────

def test_matches_by_sender(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"alerts@hdfcbank")
    result = _classify(db, sender="alerts@hdfcbank.com", subject="Alert")
    assert result.message_type == "TRANSACTION_ALERT"
    assert result.classification_id is not None


def test_sender_mismatch_returns_other(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", sender_match_regex=r"alerts@hdfcbank")
    result = _classify(db, sender="noreply@icicibank.com", subject="Alert")
    assert result.message_type == "OTHER"


# ── Subject match ─────────────────────────────────────────────────────────────

def test_matches_by_subject(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", subject_match_regex=r"(?i)account (debited|credited)")
    result = _classify(db, sender="x@y.com", subject="Your account debited with INR 500")
    assert result.message_type == "TRANSACTION_ALERT"


def test_subject_case_insensitive(db: Session) -> None:
    seed_classification(db, message_type="STATEMENT", subject_match_regex=r"(?i)statement")
    result = _classify(db, sender="x@y.com", subject="MONTHLY STATEMENT FOR MARCH 2025")
    assert result.message_type == "STATEMENT"


# ── Body match ────────────────────────────────────────────────────────────────

def test_matches_by_body(db: Session) -> None:
    seed_classification(db, message_type="TRANSACTION_ALERT", body_match_regex=r"(?i)debited with INR")
    result = _classify(db, sender="x@y.com", subject="Notification", body="Your A/c has been debited with INR 1000.")
    assert result.message_type == "TRANSACTION_ALERT"


# ── SINK ──────────────────────────────────────────────────────────────────────

def test_sink_classification(db: Session) -> None:
    seed_classification(db, message_type="SINK", subject_match_regex=r"(?i)newsletter|unsubscribe")
    result = _classify(db, sender="promo@bank.com", subject="Monthly Newsletter")
    assert result.message_type == "SINK"


# ── INVESTMENT_NOTICE ─────────────────────────────────────────────────────────

def test_investment_notice(db: Session) -> None:
    seed_classification(db, message_type="INVESTMENT_NOTICE", subject_match_regex=r"(?i)SIP|mutual fund|folio")
    result = _classify(db, sender="noreply@fundhouse.com", subject="SIP investment confirmed")
    assert result.message_type == "INVESTMENT_NOTICE"


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_higher_priority_rule_wins(db: Session) -> None:
    seed_classification(db, name="low", message_type="STATEMENT", priority=1, sender_match_regex=r"hdfc")
    seed_classification(db, name="high", message_type="TRANSACTION_ALERT", priority=99, sender_match_regex=r"hdfc")
    result = _classify(db, sender="alerts@hdfcbank.com", subject="Alert")
    assert result.message_type == "TRANSACTION_ALERT"


# ── All match conditions must pass ────────────────────────────────────────────

def test_all_specified_patterns_must_match(db: Session) -> None:
    seed_classification(
        db,
        message_type="TRANSACTION_ALERT",
        sender_match_regex=r"hdfc",
        subject_match_regex=r"(?i)debited",
    )
    # Sender matches but subject does not → OTHER
    result = _classify(db, sender="alerts@hdfcbank.com", subject="Promotional offer")
    assert result.message_type == "OTHER"

    # Both match → TRANSACTION_ALERT
    result = _classify(db, sender="alerts@hdfcbank.com", subject="Account debited")
    assert result.message_type == "TRANSACTION_ALERT"


# ── Extract regex ─────────────────────────────────────────────────────────────

def test_body_extract_regex_populates_extracted(db: Session) -> None:
    seed_classification(
        db,
        message_type="TRANSACTION_ALERT",
        sender_match_regex=r"hdfc",
        body_extract_regex=r"A/c\s+(?P<account_id>\w+)",
    )
    result = _classify(db, sender="alerts@hdfcbank.com", body="Your A/c XX5678 has been debited.")
    assert result.message_type == "TRANSACTION_ALERT"
    assert result.extracted.get("account_id") == "XX5678"


def test_subject_extract_regex_populates_extracted(db: Session) -> None:
    seed_classification(
        db,
        message_type="TRANSACTION_ALERT",
        subject_match_regex=r"(?i)alert",
        subject_extract_regex=r"INR\s*(?P<amount>[\d,]+)",
    )
    result = _classify(db, sender="x@y.com", subject="Alert: INR 750 debited")
    assert result.extracted.get("amount") == "750"


# ── Inactive rules are ignored ────────────────────────────────────────────────

def test_inactive_rule_is_ignored(db: Session) -> None:
    from backend.app.models.classification import Classification, MessageType
    row = Classification(
        name="Disabled",
        message_type=MessageType.TRANSACTION_ALERT,
        priority=100,
        sender_match_regex=r"hdfc",
        is_active=False,
    )
    db.add(row)
    db.flush()
    result = _classify(db, sender="alerts@hdfcbank.com")
    assert result.message_type == "OTHER"
