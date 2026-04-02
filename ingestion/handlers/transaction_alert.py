"""TRANSACTION_ALERT — DB-driven parser, confidence gate, ledger upsert."""

from __future__ import annotations

import logging
from typing import Optional

from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import (
    CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD,
    delete_transactions_for_mail_id,
    get_required_config_int,
    remove_unparsed,
    set_email_parser_id,
    upsert_transaction,
    upsert_unparsed,
)
logger = logging.getLogger(__name__)


class ParserAttemptError(Exception):
    """Raised when a transaction parse attempt fails."""

    def __init__(self, *, failure_reason: str, parser_id: Optional[int]) -> None:
        super().__init__(failure_reason)
        self.failure_reason = failure_reason
        self.parser_id = parser_id


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
