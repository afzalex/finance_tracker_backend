"""Dispatch classified messages to the appropriate handler."""

from __future__ import annotations

from typing import Callable

from backend.ingestion.handlers.context import HandlerContext

from . import investment, other, sink, statement, transaction_alert

_Handler = Callable[[HandlerContext], None]

_HANDLERS: dict[str, _Handler] = {
    "SINK": sink.handle,
    "TRANSACTION_ALERT": transaction_alert.handle,
    "INVESTMENT_NOTICE": investment.handle,
    "STATEMENT": statement.handle,
    "OTHER": other.handle_other,
}


def dispatch(ctx: HandlerContext) -> None:
    """Run the handler for ``ctx.result.message_type`` (unknown types → ``handle_unknown_type``)."""
    mt = ctx.result.message_type
    handler = _HANDLERS.get(mt)
    if handler is not None:
        handler(ctx)
    else:
        other.handle_unknown_type(ctx)
