"""OTHER and unknown message types — queue for review."""

from __future__ import annotations

from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import upsert_unparsed


def handle_other(ctx: HandlerContext) -> None:
    """Classifier explicitly returned OTHER."""
    upsert_unparsed(
        ctx.db,
        ctx.email,
        reason=f"classification:{ctx.result.message_type}",
        classification_id=ctx.result.classification_id,
        parser_id=None,
    )
    ctx.stats["unparsed"] += 1


def handle_unknown_type(ctx: HandlerContext) -> None:
    """Message type string not registered (should be rare)."""
    mt = ctx.result.message_type
    upsert_unparsed(
        ctx.db,
        ctx.email,
        reason=f"classification:{mt}",
        classification_id=ctx.result.classification_id,
        parser_id=None,
    )
    ctx.stats["unparsed"] += 1
