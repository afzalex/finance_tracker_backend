"""DB-driven transaction parser: rules live in the ``parsers`` table."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.parser import Parser
from backend.config import settings
from backend.ingestion.utils import match_regex, merge_extract_groups

logger = logging.getLogger(__name__)

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

_W_AMOUNT = 25
_W_DIRECTION = 20
_W_TIME = 15
_W_MERCHANT = 10
_W_TXN_ID = 10
_W_ACCOUNT_ID = 8
_W_PROVIDER = 7


@dataclass(frozen=True, slots=True)
class ParserRuleSnapshot:
    """In-memory copy of a ``parsers`` row — no ORM lazy loads during match/extract."""

    id: int
    name: str
    label: str
    sender_match_regex: Optional[str]
    subject_match_regex: Optional[str]
    body_match_regex: Optional[str]
    subject_extract_regex: Optional[str]
    body_extract_regex: Optional[str]
    snippet_extract_regex: Optional[str]
    txn_date_fmt: Optional[str]
    txn_time_fmt: Optional[str]
    provider: Optional[str]
    account_type: Optional[str]
    transaction_type: Optional[str]
    sub_type: Optional[str]
    status: Optional[str]


@dataclass
class ParseResult:
    """Outcome of parsing one email with a parser rule."""

    success: bool
    fields: dict = field(default_factory=dict)
    parser_id: Optional[int] = None
    failure_reason: Optional[str] = None


class TransactionParser:
    """Match ``parsers`` rows against an email and extract named groups."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._parsers: list[ParserRuleSnapshot] = []
        self._extract_regex_cache: dict[str, re.Pattern[str]] = {}

    def load_parsers(self) -> None:
        self._extract_regex_cache.clear()
        rows = (
            self.db.query(Parser)
            .filter(Parser.is_active.is_(True))
            .order_by(Parser.priority.desc())
            .all()
        )
        self._parsers = [
            ParserRuleSnapshot(
                id=p.id,
                name=p.name,
                label=p.label,
                sender_match_regex=p.sender_match_regex,
                subject_match_regex=p.subject_match_regex,
                body_match_regex=p.body_match_regex,
                subject_extract_regex=p.subject_extract_regex,
                body_extract_regex=p.body_extract_regex,
                snippet_extract_regex=p.snippet_extract_regex,
                txn_date_fmt=p.txn_date_fmt,
                txn_time_fmt=p.txn_time_fmt,
                provider=p.provider,
                account_type=p.account_type,
                transaction_type=p.transaction_type,
                sub_type=p.sub_type,
                status=p.status,
            )
            for p in rows
        ]
        logger.debug("Loaded %d parser rules", len(self._parsers))

    def _compile_extract_pattern(self, pattern: str) -> re.Pattern[str]:
        if pattern not in self._extract_regex_cache:
            self._extract_regex_cache[pattern] = re.compile(
                pattern, re.IGNORECASE | re.DOTALL
            )
        return self._extract_regex_cache[pattern]

    @staticmethod
    def _body_text_for_extract(body: str) -> str:
        limit = settings.max_body_extract_chars
        if limit <= 0 or len(body) <= limit:
            return body
        logger.debug(
            "Truncating body for extract regex: %d -> %d chars (max_body_extract_chars)",
            len(body),
            limit,
        )
        return body[:limit]

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
        """Try each loaded parser in priority order.

        Returns the first successful ``ParseResult``. If no row matches, failure_reason is
        ``no_parser_matched``. If at least one row matched but extraction never succeeded,
        returns the last such failure (e.g. ``missing_direction``).
        """
        sender = sender or ""
        subject = subject or ""
        body = (body or "").replace("\r", "")
        snippet = snippet or ""

        last_matched_failure: Optional[ParseResult] = None

        for row in self._parsers:
            if not self._matches(row, sender, subject, body):
                continue

            pname, pid = row.name, row.id
            logger.debug("Extracting with parser %r (id=%d)", pname, pid)
            try:
                result = self._extract(
                    row, sender, subject, body, snippet, internal_date_ms, classification_id
                )
            except Exception:
                logger.exception("Error extracting with parser %r (id=%d)", pname, pid)
                continue

            if result.success:
                logger.debug("Extracted with parser %r (id=%d)", pname, pid)
                return result

            last_matched_failure = result
            logger.error(
                "Failed to extract with parser %r (id=%d): %s",
                pname,
                pid,
                result.failure_reason,
            )

        # After the loop: either no row matched (_matches), or some row matched but every
        # extract attempt failed — in the latter case return that failure (e.g. missing_amount).
        return (
            last_matched_failure
            if last_matched_failure is not None
            else ParseResult(success=False, failure_reason="no_parser_matched")
        )

    def _matches(self, row: ParserRuleSnapshot, sender: str, subject: str, body: str) -> bool:
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
        row: ParserRuleSnapshot,
        sender: str,
        subject: str,
        body: str,
        snippet: str,
        internal_date_ms: int,
        classification_id: Optional[int],
    ) -> ParseResult:
        parser_id = row.id

        body_re = (row.body_extract_regex or "").strip()
        subject_re = (row.subject_extract_regex or "").strip()
        snippet_re = (row.snippet_extract_regex or "").strip()

        if not body_re and not subject_re and not snippet_re:
            return ParseResult(success=False, parser_id=parser_id, failure_reason="no_extract_regex")

        body_for_extract = self._body_text_for_extract(body)
        body_m = (
            self._compile_extract_pattern(body_re).search(body_for_extract) if body_re else None
        )
        subject_m = (
            self._compile_extract_pattern(subject_re).search(subject) if subject_re else None
        )
        snippet_m = (
            self._compile_extract_pattern(snippet_re).search(snippet) if snippet_re else None
        )

        if not ((body_re and body_m) or (subject_re and subject_m) or (snippet_re and snippet_m)):
            return ParseResult(success=False, parser_id=parser_id, failure_reason="no_regex_match")

        g = merge_extract_groups(body_m, subject_m, snippet_m)
        g = {k: g[k] for k in _EXTRACT_GROUP_NAMES if k in g}

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

        amount_raw = g.get("amount") or g.get("txn_amount") or ""
        amount_parsed = _parse_amount(amount_raw)
        if amount_parsed is None or amount_parsed <= 0:
            return ParseResult(success=False, parser_id=parser_id, failure_reason="missing_amount")

        transacted_at = _parse_datetime(
            g.get("time"),
            g.get("txn_date"),
            g.get("txn_time"),
            row.txn_date_fmt,
            row.txn_time_fmt,
            internal_date_ms,
        )

        def _row_or_group(field_name: str, row_val: Optional[str]) -> Optional[str]:
            v = _trim(g.get(field_name))
            return v if v else _trim(row_val)

        provider = _row_or_group("provider", row.provider) or _trim(row.label)
        account_type = _row_or_group("account_type", row.account_type)
        transaction_type = _row_or_group("transaction_type", row.transaction_type)
        sub_type = _row_or_group("sub_type", row.sub_type)
        status = _row_or_group("status", row.status) or "UNKNOWN"

        account_id = _trim(g.get("account_id"))
        account_last4 = _trim(g.get("account_last4"))
        card_last4 = _trim(g.get("card_last4"))

        if not account_id:
            account_id = _find_account_suffix(body, subject, snippet)
        if not account_id:
            account_id = account_last4 or card_last4

        fields: Dict[str, Any] = {
            "mail_id": None,
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


def _parse_amount(raw: Optional[str]) -> Optional[Decimal]:
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
    fallback = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)

    if time_str:
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

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
    if raw and ("inr" in raw.lower() or "rs" in raw.lower() or "₹" in raw):
        return "INR"
    return "INR"


def _find_account_suffix(body: str, subject: str, snippet: str) -> Optional[str]:
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
    if not s or not s.strip():
        return None
    return s.strip()[:max_len]


def _compute_confidence(fields: dict) -> int:
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
