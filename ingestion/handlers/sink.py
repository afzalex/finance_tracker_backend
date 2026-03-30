"""Handler for SINK messages — discard from user workflow, clear unparsed."""

from __future__ import annotations

from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import remove_unparsed


def handle(ctx: HandlerContext) -> None:
    ctx.stats["skipped"] += 1
    remove_unparsed(ctx.db, ctx.email.fetched_email_id)
