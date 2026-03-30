"""Post-classification message handlers (per ``MessageType``)."""

from backend.ingestion.handlers.registry import dispatch

__all__ = ["dispatch"]
