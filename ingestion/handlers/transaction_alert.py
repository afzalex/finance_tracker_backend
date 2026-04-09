"""TRANSACTION_ALERT — DB-driven parser, confidence gate, ledger upsert."""

from __future__ import annotations

import logging
import json
from typing import Optional

from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import (
    CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD,
    delete_transactions_for_mail_id,
    get_required_config_int,
    remove_unparsed,
    set_email_exclusion_rule_id,
    set_email_parser_id,
    upsert_transaction,
    upsert_unparsed,
)
import re
from sqlalchemy import select
from backend.app.models.exclusion_rule import ExclusionRule

logger = logging.getLogger(__name__)


class ParserAttemptError(Exception):
    """Raised when a transaction parse attempt fails."""

    def __init__(self, *, failure_reason: str, parser_id: Optional[int]) -> None:
        super().__init__(failure_reason)
        self.failure_reason = failure_reason
        self.parser_id = parser_id


def _parse_csv_ints(csv: str | None) -> list[int]:
    """Parse a comma-separated string of ints (e.g. ``parser_ids``)."""
    if not csv or not csv.strip():
        return []
    out: list[int] = []
    for p in csv.split(","):
        p = p.strip()
        if p:
            try:
                out.append(int(p))
            except ValueError:
                continue
    return out


def handle(ctx: HandlerContext) -> None:
    delete_transactions_for_mail_id(ctx.db, ctx.email.mail_id)

    result = ctx.result
    parse_result = ctx.parser.parse(
        ctx.email.sender,
        ctx.email.subject,
        ctx.email.body_text,
        ctx.email.snippet,
        ctx.email.internal_date_ms,
        result.message_type,
        result.classification_id,
    )

    set_email_parser_id(ctx.db, ctx.email.fetched_email_id, parse_result.parser_id)

    try:
        if not parse_result.success:
            raise ParserAttemptError(
                failure_reason=parse_result.failure_reason or "parse_failed",
                parser_id=parse_result.parser_id,
            )

        fields = parse_result.fields
        confidence = fields.get("confidence", 0)
        threshold = get_required_config_int(
            ctx.db, CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD, min_value=0
        )
        if confidence < threshold:
            raise ParserAttemptError(
                failure_reason=f"low_confidence:{confidence}<{threshold}",
                parser_id=parse_result.parser_id,
            )

        fields["mail_id"] = ctx.email.mail_id
        
        # Check exclusion rules

        stmt = select(ExclusionRule).where(ExclusionRule.is_active.is_(True))
        rules = ctx.db.scalars(stmt).all()
        is_ex = False
        matched_rule_id = None
        
        tx_merchant = (fields.get("merchant") or "").strip().casefold()
        tx_counterparty = (fields.get("counterparty_name") or "").strip().casefold()

        for rule in rules:
            rule_parser_ids = _parse_csv_ints(rule.parser_ids)
            parser_match = bool(rule_parser_ids and parse_result.parser_id in rule_parser_ids)

            payee_match = False
            if rule.payees:
                try:
                    rule_payees = [str(x).strip().casefold() for x in json.loads(rule.payees)]
                    if (tx_merchant and tx_merchant in rule_payees) or (tx_counterparty and tx_counterparty in rule_payees):
                        payee_match = True
                except Exception:
                    pass

            if parser_match or payee_match:
                is_ex = True
                matched_rule_id = rule.id
                break
        
        fields["is_excluded"] = is_ex
        fields["exclusion_rule_id"] = matched_rule_id

        # Record exclusion rule on enrichment
        set_email_exclusion_rule_id(ctx.db, ctx.email.fetched_email_id, matched_rule_id)

        saved = upsert_transaction(ctx.db, fields)
        if saved == "duplicate":
            ctx.stats["duplicate"] += 1
            remove_unparsed(ctx.db, ctx.email.fetched_email_id)
        else:
            ctx.stats["parsed"] += 1
            remove_unparsed(ctx.db, ctx.email.fetched_email_id)
    except ParserAttemptError as exc:
        upsert_unparsed(
            ctx.db,
            ctx.email,
            reason=exc.failure_reason,
            classification_id=result.classification_id,
            parser_id=exc.parser_id,
        )
        ctx.stats["unparsed"] += 1
