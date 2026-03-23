"""Tests for TransactionParser — DB-driven transaction extraction."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from backend.ingestion.parsers import ParseResult, TransactionParser, _parse_amount, _compute_confidence
from tests.conftest import seed_parser

# Epoch timestamp matching 2024-03-01 00:00:00 UTC
_TS_MS = 1_709_251_200_000

# A realistic HDFC debit alert body
_HDFC_BODY = (
    "Dear Customer, Your HDFC Bank A/c XX1234 has been debited with INR 999.00 "
    "on 01-03-2024. Info: SWIGGY. Avl Bal: INR 10,000.00."
)

# Regex that captures the key fields from the above body
_HDFC_REGEX = (
    r"A/c\s+(?P<account_id>\w+)\s+has been\s+(?P<txn_isdebit>debited)\s+with\s+"
    r"INR\s+(?P<amount>[\d,]+\.?\d*)\s+on\s+(?P<txn_date>\d{2}-\d{2}-\d{4})\."
    r".*?Info:\s+(?P<merchant>[^.]+)\."
)


def _parse(db: Session, sender: str = "", subject: str = "", body: str = "",
           snippet: str = "", internal_date_ms: int = _TS_MS) -> ParseResult:
    p = TransactionParser(db)
    p.load_parsers()
    return p.parse(sender, subject, body, snippet, internal_date_ms, "TRANSACTION_ALERT")


# ── No parsers → failure ──────────────────────────────────────────────────────

def test_no_parsers_returns_failure(db: Session) -> None:
    result = _parse(db, body=_HDFC_BODY)
    assert result.success is False
    assert result.failure_reason == "no_parser_matched"


# ── Sender matching ───────────────────────────────────────────────────────────

def test_parser_matches_by_sender(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfcbank", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com", body=_HDFC_BODY)
    assert result.success is True


def test_parser_skips_non_matching_sender(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfcbank", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@icicibank.com", body=_HDFC_BODY)
    assert result.success is False


# ── Field extraction ──────────────────────────────────────────────────────────

def test_extracts_amount_and_direction(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfc", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com", body=_HDFC_BODY)
    assert result.success is True
    assert result.fields["amount_parsed"] == 999.0
    assert result.fields["direction"] == "DEBIT"


def test_extracts_account_id(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfc", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com", body=_HDFC_BODY)
    assert result.fields["account_id"] == "XX1234"


def test_extracts_merchant(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfc", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com", body=_HDFC_BODY)
    assert result.fields["merchant"] == "SWIGGY"


def test_provider_from_parser_row_default(db: Session) -> None:
    seed_parser(db, sender_match_regex=r"hdfc", body_extract_regex=_HDFC_REGEX, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com", body=_HDFC_BODY)
    assert result.fields["provider"] == "HDFC"


def test_provider_from_regex_group_overrides_row(db: Session) -> None:
    regex = r"(?P<txn_isdebit>debited)\s+(?P<amount>[\d.]+).*?(?P<provider>MYBANK)"
    seed_parser(db, sender_match_regex=r"mybank", body_extract_regex=regex, provider="FALLBACK")
    result = _parse(db, sender="alerts@mybank.com",
                    body="Account debited 100.00 by MYBANK")
    assert result.fields["provider"] == "MYBANK"


# ── Direction variants ────────────────────────────────────────────────────────

def test_credit_via_txn_iscredit_group(db: Session) -> None:
    regex = r"(?P<txn_iscredit>credited)\s+INR\s+(?P<amount>[\d.]+)"
    seed_parser(db, sender_match_regex=r"hdfc", body_extract_regex=regex, provider="HDFC")
    result = _parse(db, sender="alerts@hdfcbank.com",
                    body="Your account has been credited INR 2000.00")
    assert result.success is True
    assert result.fields["direction"] == "CREDIT"


def test_debit_via_direction_group(db: Session) -> None:
    regex = r"(?P<amount>[\d.]+) (?P<direction>DR|CR)"
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="500.00 DR")
    assert result.fields["direction"] == "DEBIT"

    result2 = _parse(db, sender="x@bank.com", body="500.00 CR")
    assert result2.fields["direction"] == "CREDIT"


def test_missing_direction_returns_failure(db: Session) -> None:
    regex = r"amount\s+(?P<amount>[\d.]+)"  # no direction group
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="amount 100.00")
    assert result.success is False
    assert result.failure_reason == "missing_direction"


# ── Amount edge cases ─────────────────────────────────────────────────────────

def test_missing_amount_returns_failure(db: Session) -> None:
    regex = r"(?P<txn_isdebit>debited)"
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="Your account has been debited.")
    assert result.success is False
    assert result.failure_reason == "missing_amount"


def test_parse_amount_handles_indian_commas() -> None:
    assert _parse_amount("Rs. 1,23,456.78") is not None
    assert float(_parse_amount("Rs. 1,23,456.78")) == pytest.approx(123456.78)


def test_parse_amount_handles_plain_integer() -> None:
    assert float(_parse_amount("500")) == 500.0


def test_parse_amount_returns_none_for_zero() -> None:
    assert _parse_amount("0") is None
    assert _parse_amount("Rs 0.00") is None


def test_parse_amount_returns_none_for_garbage() -> None:
    assert _parse_amount("no digits") is None
    assert _parse_amount(None) is None


# ── Timestamp fallback ────────────────────────────────────────────────────────

def test_falls_back_to_internal_date_when_no_date_group(db: Session) -> None:
    regex = r"(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d.]+)"
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="Account debited INR 100.00",
                    internal_date_ms=_TS_MS)
    expected = datetime.fromtimestamp(_TS_MS / 1000.0, tz=timezone.utc)
    assert result.fields["transacted_at"] == expected


def test_uses_txn_date_group_when_present(db: Session) -> None:
    regex = (
        r"(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d.]+)\s+on\s+"
        r"(?P<txn_date>\d{2}/\d{2}/\d{4})"
    )
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK",
                txn_date_fmt="%d/%m/%Y")
    result = _parse(db, sender="x@bank.com",
                    body="Account debited INR 500.00 on 15/03/2024")
    dt: datetime = result.fields["transacted_at"]
    assert dt.day == 15
    assert dt.month == 3
    assert dt.year == 2024


# ── Confidence scoring ────────────────────────────────────────────────────────

def test_full_confidence_with_all_fields() -> None:
    fields = {
        "amount_parsed": 500.0,
        "direction": "DEBIT",
        "transacted_at": datetime.now(tz=timezone.utc),
        "merchant": "Swiggy",
        "txn_id": "TXN123",
        "account_id": "XX1234",
        "provider": "HDFC",
    }
    assert _compute_confidence(fields) == 95


def test_minimum_confidence_with_only_amount_and_direction() -> None:
    fields = {
        "amount_parsed": 100.0,
        "direction": "CREDIT",
        "transacted_at": None,
        "merchant": None,
        "txn_id": None,
        "account_id": None,
        "provider": None,
    }
    assert _compute_confidence(fields) == 45  # 25 + 20


def test_confidence_zero_when_no_fields() -> None:
    assert _compute_confidence({}) == 0


# ── account_id fallback ───────────────────────────────────────────────────────

def test_account_id_falls_back_to_account_last4(db: Session) -> None:
    # No account_id group, but account_last4 present
    regex = r"card\s+(?P<account_last4>\d{4})\s+(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d.]+)"
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="card 5678 debited INR 300.00")
    assert result.fields["account_id"] == "5678"


def test_account_id_falls_back_to_ac_pattern_in_body(db: Session) -> None:
    regex = r"(?P<txn_isdebit>debited)\s+INR\s+(?P<amount>[\d.]+)"
    seed_parser(db, sender_match_regex=r"bank", body_extract_regex=regex, provider="BANK")
    result = _parse(db, sender="x@bank.com", body="A/c XX9999 debited INR 200.00")
    assert result.fields["account_id"] == "XX9999"


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_higher_priority_parser_wins(db: Session) -> None:
    regex = r"(?P<txn_isdebit>debited)\s+(?P<amount>[\d.]+)"
    seed_parser(db, name="low", sender_match_regex=r"bank", body_extract_regex=regex,
                provider="LOW", priority=1)
    seed_parser(db, name="high", sender_match_regex=r"bank", body_extract_regex=regex,
                provider="HIGH", priority=99)
    result = _parse(db, sender="x@bank.com", body="Account debited 100.00")
    assert result.fields["provider"] == "HIGH"


# ── Inactive parsers are skipped ──────────────────────────────────────────────

def test_inactive_parser_is_skipped(db: Session) -> None:
    from backend.app.models.parser import Parser
    row = Parser(
        name="Disabled", label="X", priority=10,
        sender_match_regex=r"bank",
        body_extract_regex=r"(?P<txn_isdebit>debited)\s+(?P<amount>[\d.]+)",
        provider="BANK",
        is_active=False,
    )
    db.add(row)
    db.flush()
    result = _parse(db, sender="x@bank.com", body="Account debited 100.00")
    assert result.success is False
