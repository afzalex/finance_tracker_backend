"""DB-driven transaction parsers.

Parsers are defined entirely in the database (``parsers`` table).
Adding support for a new bank/notification format requires only inserting a row
— no code changes.

Mandatory extracted fields (if any missing → message goes to unparsed queue):
  amount      Numeric transaction amount.
  direction   DEBIT or CREDIT.
  provider    Bank or app name (e.g. HDFC, PhonePe).
  account_id  Account/card identifier (e.g. masked last 4 digits).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.parser import Parser
from backend.ingestion.utils import match_regex, merge_extract_groups

logger = logging.getLogger(__name__)

# Named groups the extract regexes may capture
_EXTRACT_GROUP_NAMES = (
    "time", "txn_date", "txn_time",
    "amount", "txn_amount", "currency",
    "txn_isdebit", "txn_iscredit", "direction",
    "provider", "account_id", "txn_id",
    "transaction_type", "sub_type", "status",
    "fee_amount", "account_type",
    "account_last4", "card_last4", "card_network", "card_brand",
    "merchant",
    "counterparty_name", "counterparty_vpa", "counterparty_account",
    "counterparty_number", "counterparty_id",
    "category", "balance", "reward_points",
)

# Confidence score weights
_W_AMOUNT = 25
_W_DIRECTION = 20
_W_TIME = 15
_W_MERCHANT = 10
_W_TXN_ID = 10
_W_ACCOUNT_ID = 8
_W_PROVIDER = 7


@dataclass
class ParseResult:
    """Result of attempting to parse a transaction from an email."""
    success: bool
    fields: dict = field(default_factory=dict)
    parser_id: Optional[int] = None
    failure_reason: Optional[str] = None


class TransactionParser:
    """Attempts to parse transaction fields from a classified email.

    Implements the DB-driven parser system: loads ``parsers`` table rows,
    matches each email against parser rules, and extracts named groups.
    Named-group captures take precedence over per-row defaults.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._parsers: list[Parser] = []

    def load_parsers(self) -> None:
        """Load active parser rows from the DB ordered by priority descending."""
        self._parsers = (
            self.db.query(Parser)
            .filter(Parser.is_active.is_(True))
            .order_by(Parser.priority.desc())
            .all()
        )
        logger.debug("Loaded %d parser rules", len(self._parsers))

    def parse(
        self,
        sender: str,
        subject: str,
        body: str,
        snippet: str,
        internal_date_ms: int,
        message_type: str,
        classification_id: Optional[int] = None,
    ) -> ParseResult:
        """Try each loaded parser against the email; return first successful match."""
        sender = sender or ""
        subject = subject or ""
        body = (body or "").replace("\r", "")
        snippet = snippet or ""

        for parser_row in self._parsers:
            if not self._matches(parser_row, sender, subject, body):
                continue

            result = self._extract(
                parser_row, sender, subject, body, snippet, internal_date_ms, classification_id
            )
            if result.success:
                logger.debug(
                    "Parsed with parser %r (id=%d) confidence=%d",
                    parser_row.name, parser_row.id, result.fields.get("confidence", 0),
                )
            return result

        return ParseResult(success=False, failure_reason="no_parser_matched")

    # ── Private ───────────────────────────────────────────────────────────────

    def _matches(self, row: Parser, sender: str, subject: str, body: str) -> bool:
        """Return True if the parser's match regexes all pass for the given email fields.

        A parser matches when:
        - No match regex is ``None`` / empty AND evaluates to ``False``, AND
        - At least one match regex is non-empty (parsers with no criteria at all are skipped).
        """
        results = tuple(
            match_regex(pattern, text, empty_means_match=False)
            for pattern, text in (
                (row.sender_match_regex, sender),
                (row.subject_match_regex, subject),
                (row.body_match_regex, body),
            )
        )
        return not (any(r is False for r in results) or all(r is None for r in results))

    def _extract(
        self,
        row: Parser,
        sender: str,
        subject: str,
        body: str,
        snippet: str,
        internal_date_ms: int,
        classification_id: Optional[int],
    ) -> ParseResult:
        """Run the parser's extract regexes against the email and build a ``ParseResult``.

        Extraction steps:
        1. Run ``body_extract_regex``, ``subject_extract_regex``, and
           ``snippet_extract_regex`` (whichever are configured).
        2. Merge named groups with body > subject > snippet precedence.
        3. Resolve ``direction`` from ``txn_isdebit`` / ``txn_iscredit`` / ``direction`` groups.
        4. Parse ``amount`` / ``txn_amount`` into a positive ``Decimal``.
        5. Derive ``transacted_at`` from date/time groups or fall back to ``internal_date_ms``.
        6. Apply parser-row defaults for ``provider``, ``account_type``, etc. when the
           corresponding named groups are absent.
        7. Run ``_find_account_suffix`` as a last-resort ``account_id`` fallback.
        8. Compute and attach a confidence score.

        Returns a ``ParseResult`` with ``success=False`` and a ``failure_reason`` string
        when any mandatory field (direction, amount) cannot be determined.
        """
        parser_id = row.id

        body_re = (row.body_extract_regex or "").strip()
        subject_re = (row.subject_extract_regex or "").strip()
        snippet_re = (row.snippet_extract_regex or "").strip()

        if not body_re and not subject_re and not snippet_re:
            return ParseResult(success=False, parser_id=parser_id, failure_reason="no_extract_regex")

        body_m = re.search(body_re, body, re.IGNORECASE | re.DOTALL) if body_re else None
        subject_m = re.search(subject_re, subject, re.IGNORECASE | re.DOTALL) if subject_re else None
        snippet_m = re.search(snippet_re, snippet, re.IGNORECASE | re.DOTALL) if snippet_re else None

        if not ((body_re and body_m) or (subject_re and subject_m) or (snippet_re and snippet_m)):
            return ParseResult(success=False, parser_id=parser_id, failure_reason="no_regex_match")

        g = merge_extract_groups(body_m, subject_m, snippet_m)
        g = {k: g[k] for k in _EXTRACT_GROUP_NAMES if k in g}

        # ── Direction ─────────────────────────────────────────────────────────
        direction: Optional[str] = None
        if "txn_isdebit" in g:
            direction = "DEBIT"
        elif "txn_iscredit" in g:
            direction = "CREDIT"
        if not direction and g.get("direction"):
            d = g["direction"].upper()
            if "DEBIT" in d or d == "DR":
                direction = "DEBIT"
            elif "CREDIT" in d or d == "CR":
                direction = "CREDIT"
        if not direction:
            return ParseResult(success=False, parser_id=parser_id, failure_reason="missing_direction")

        # ── Amount ────────────────────────────────────────────────────────────
        amount_raw = g.get("amount") or g.get("txn_amount") or ""
        amount_parsed = _parse_amount(amount_raw)
        if amount_parsed is None or amount_parsed <= 0:
            return ParseResult(success=False, parser_id=parser_id, failure_reason="missing_amount")

        # ── Timestamp ─────────────────────────────────────────────────────────
        transacted_at = _parse_datetime(
            g.get("time"),
            g.get("txn_date"),
            g.get("txn_time"),
            row.txn_date_fmt,
            row.txn_time_fmt,
            internal_date_ms,
        )

        # ── Parser-row defaults (regex group overrides when present) ──────────
        def _row_or_group(field_name: str, row_val: Optional[str]) -> Optional[str]:
            v = _trim(g.get(field_name))
            return v if v else _trim(row_val)

        provider = _row_or_group("provider", row.provider) or _trim(row.label)
        account_type = _row_or_group("account_type", row.account_type)
        transaction_type = _row_or_group("transaction_type", row.transaction_type)
        sub_type = _row_or_group("sub_type", row.sub_type)
        status = _row_or_group("status", row.status) or "UNKNOWN"

        # ── Account identification ─────────────────────────────────────────────
        account_id = _trim(g.get("account_id"))
        account_last4 = _trim(g.get("account_last4"))
        card_last4 = _trim(g.get("card_last4"))

        # Fallback: search for "a/c XXXX" pattern
        if not account_id:
            account_id = _find_account_suffix(body, subject, snippet)
        if not account_id:
            account_id = account_last4 or card_last4

        fields: Dict[str, Any] = {
            "gmail_message_id": None,  # filled in by pipeline
            "transacted_at": transacted_at,
            "origin": "EMAIL_ALERT",
            "amount": amount_raw,
            "amount_parsed": float(amount_parsed),
            "currency": _normalize_currency(g.get("currency") or amount_raw),
            "direction": direction,
            "provider": provider,
            "account_type": account_type,
            "account_id": account_id,
            "account_last4": account_last4,
            "card_last4": card_last4,
            "card_network": _trim(g.get("card_network")),
            "card_brand": _trim(g.get("card_brand")),
            "transaction_type": transaction_type,
            "sub_type": sub_type,
            "status": status,
            "txn_id": _trim(g.get("txn_id")),
            "fee_amount": float(_parse_amount(g.get("fee_amount")) or 0) or None,
            "merchant": _trim(g.get("merchant")),
            "counterparty_name": _trim(g.get("counterparty_name")),
            "counterparty_vpa": _trim(g.get("counterparty_vpa")),
            "counterparty_account": _trim(g.get("counterparty_account")),
            "counterparty_number": _trim(g.get("counterparty_number")),
            "counterparty_id": _trim(g.get("counterparty_id")),
            "category": _trim(g.get("category")),
            "balance": float(_parse_amount(g.get("balance")) or 0) or None,
            "reward_points": float(_parse_amount(g.get("reward_points")) or 0) or None,
            "parser_id": parser_id,
            "classification_id": classification_id,
        }

        fields["confidence"] = _compute_confidence(fields)
        return ParseResult(success=True, fields=fields, parser_id=parser_id)


# ── Module-level helpers ───────────────────────────────────────────────────────

def _parse_amount(raw: Optional[str]) -> Optional[Decimal]:
    """Extract the first numeric value from a raw amount string.

    Accepts strings like ``"INR 1,234.56"``, ``"Rs.500"``, ``"1000.00"``.
    Returns ``None`` when no positive number can be found.
    """
    if not raw:
        return None
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw)
    if not m:
        return None
    try:
        amount = Decimal(m.group(1).replace(",", ""))
        return amount if amount > 0 else None
    except InvalidOperation:
        return None


def _parse_datetime(
    time_str: Optional[str],
    date_str: Optional[str],
    time_only_str: Optional[str],
    date_fmt: Optional[str],
    time_fmt: Optional[str],
    internal_date_ms: int,
) -> datetime:
    """Resolve a transaction timestamp from extracted regex groups.

    Resolution order:
    1. ``time_str`` as a full ISO 8601 datetime.
    2. ``date_str`` (or ``time_str``) parsed with ``date_fmt``, combined with
       ``time_only_str`` parsed with ``time_fmt``.
    3. Date-only result when no time component can be parsed.
    4. Time component overlaid on the ``internal_date_ms`` fallback when only a
       time is available.
    5. ``internal_date_ms`` converted to UTC datetime as the final fallback.

    Always returns a timezone-aware datetime (UTC).
    """
    fallback = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)

    # 1. ISO 8601 full datetime
    if time_str:
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # 2. Date + optional time parts
    date_dt = _parse_date(date_str or time_str, date_fmt)
    time_tup = _parse_time(time_only_str, time_fmt)

    if date_dt and time_tup:
        h, mi, s = time_tup
        return date_dt.replace(hour=h, minute=mi, second=s)
    if date_dt:
        return date_dt
    if time_tup:
        h, mi, s = time_tup
        return fallback.replace(hour=h, minute=mi, second=s)

    return fallback


def _parse_date(s: Optional[str], fmt: Optional[str]) -> Optional[datetime]:
    """Parse a date string using an optional ``strptime`` format, with a DD/MM/YYYY fallback.

    Returns a UTC-aware ``datetime`` at midnight, or ``None`` if parsing fails.
    """
    if not s:
        return None
    s = s.strip()
    if fmt:
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_time(s: Optional[str], fmt: Optional[str]) -> Optional[tuple[int, int, int]]:
    """Parse a time string into an ``(hour, minute, second)`` tuple.

    Tries the supplied ``strptime`` format first, then falls back to
    ``HH:MM[:SS]`` regex matching.  Returns ``None`` if the string cannot
    be parsed or the values are out of range.
    """
    if not s:
        return None
    s = s.strip()
    if fmt:
        try:
            dt = datetime.strptime(s, fmt)
            return (dt.hour, dt.minute, dt.second)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        sec = int(m.group(3)) if m.group(3) else 0
        if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= sec <= 59:
            return (h, mi, sec)
    return None


def _normalize_currency(raw: Optional[str]) -> str:
    """Map a raw currency string (e.g. ``"INR"``, ``"Rs"``, ``"₹"``) to an ISO code.

    Defaults to ``"INR"`` when the currency cannot be determined — appropriate
    for the current Indian bank notification corpus.
    """
    if raw and ("inr" in raw.lower() or "rs" in raw.lower() or "₹" in raw):
        return "INR"
    return "INR"


def _find_account_suffix(body: str, subject: str, snippet: str) -> Optional[str]:
    """Search body, subject, and snippet for an "A/c XXXX" account identifier.

    Searches in order (body first) and returns the first non-empty capture,
    e.g. ``"XX9999"`` or ``"****1234"``.  Returns ``None`` when no pattern matches.
    """
    for text in (body, subject, snippet):
        if not text:
            continue
        m = re.search(r"a/c\s*([*A-Za-z0-9]+)", text, re.IGNORECASE)
        if m:
            v = m.group(1).strip()
            if v:
                return v
    return None


def _trim(s: Optional[str], max_len: int = 500) -> Optional[str]:
    """Strip whitespace and truncate a string; return ``None`` for blank/empty input."""
    if not s or not s.strip():
        return None
    return s.strip()[:max_len]


def _compute_confidence(fields: dict) -> int:
    """Score a parsed field dict on a 0–100 scale based on which high-value fields are present.

    Weights:
        amount_parsed  25
        direction      20
        transacted_at  15
        merchant       10
        txn_id         10
        account_id      8
        provider        7
        ─────────────────
        maximum        95  (capped to 100)
    """
    score = 0
    if fields.get("amount_parsed") and float(fields["amount_parsed"]) > 0:
        score += _W_AMOUNT
    if fields.get("direction"):
        score += _W_DIRECTION
    if fields.get("transacted_at"):
        score += _W_TIME
    if fields.get("merchant"):
        score += _W_MERCHANT
    if fields.get("txn_id"):
        score += _W_TXN_ID
    if fields.get("account_id"):
        score += _W_ACCOUNT_ID
    if fields.get("provider"):
        score += _W_PROVIDER
    return min(score, 100)
