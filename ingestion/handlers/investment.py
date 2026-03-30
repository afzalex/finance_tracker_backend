"""INVESTMENT_NOTICE — placeholder until dedicated investment parsing exists."""

from __future__ import annotations

from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import upsert_unparsed


def handle(ctx: HandlerContext) -> None:
    upsert_unparsed(
        ctx.db,
        ctx.email,
        reason=f"classification:{ctx.result.message_type}",
        classification_id=ctx.result.classification_id,
        parser_id=None,
    )
    ctx.stats["unparsed"] += 1
