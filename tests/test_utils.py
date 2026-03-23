"""Tests for ingestion.utils regex helpers."""

import re

from backend.ingestion.utils import match_regex, merge_extract_groups


# ── match_regex ───────────────────────────────────────────────────────────────

def test_match_regex_matches() -> None:
    assert match_regex(r"alert", "Transaction alert received") is True


def test_match_regex_no_match() -> None:
    assert match_regex(r"hdfc", "alerts@icicibank.com") is False


def test_match_regex_case_insensitive() -> None:
    assert match_regex(r"HDFC", "alerts@hdfcbank.com") is True


def test_match_regex_empty_pattern_returns_true_by_default() -> None:
    assert match_regex(None, "anything") is True
    assert match_regex("", "anything") is True


def test_match_regex_empty_pattern_returns_none_when_no_match_mode() -> None:
    assert match_regex(None, "anything", empty_means_match=False) is None
    assert match_regex("", "anything", empty_means_match=False) is None


def test_match_regex_empty_text() -> None:
    assert match_regex(r"hdfc", "") is False


def test_match_regex_dotall() -> None:
    # Pattern should match across newlines
    assert match_regex(r"debited.+INR", "Your account\nhas been debited with\nINR 500") is True


# ── merge_extract_groups ──────────────────────────────────────────────────────

def _match(pattern: str, text: str) -> re.Match:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL)


def test_merge_body_takes_precedence_over_subject() -> None:
    body_m = _match(r"(?P<amount>500)", "INR 500")
    subject_m = _match(r"(?P<amount>100)", "INR 100")
    result = merge_extract_groups(body_m, subject_m, None)
    assert result["amount"] == "500"


def test_merge_falls_back_to_subject_when_body_empty() -> None:
    body_m = _match(r"(?P<amount>\d+)", "no digits here")  # won't capture
    subject_m = _match(r"(?P<amount>\d+)", "INR 250")
    result = merge_extract_groups(body_m, subject_m, None)
    assert result["amount"] == "250"


def test_merge_falls_back_to_snippet() -> None:
    snippet_m = _match(r"(?P<txn_id>TXN\d+)", "ref TXN12345")
    result = merge_extract_groups(None, None, snippet_m)
    assert result["txn_id"] == "TXN12345"


def test_merge_none_matches_returns_empty() -> None:
    assert merge_extract_groups(None, None, None) == {}


def test_merge_strips_whitespace_from_values() -> None:
    body_m = _match(r"(?P<merchant>\s*Swiggy\s*)", "  Swiggy  ")
    result = merge_extract_groups(body_m, None, None)
    assert result["merchant"] == "Swiggy"


def test_merge_ignores_empty_captured_groups() -> None:
    # Pattern has two groups; only one will capture
    body_m = _match(r"(?P<txn_isdebit>debited)?(?P<txn_iscredit>credited)?", "debited")
    result = merge_extract_groups(body_m, None, None)
    assert "txn_isdebit" in result
    assert "txn_iscredit" not in result
