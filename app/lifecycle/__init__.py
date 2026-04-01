"""Application lifecycle hooks (startup/shutdown)."""

from backend.app.lifecycle.scheduled_ingest import scheduled_ingest_lifespan

__all__ = ["scheduled_ingest_lifespan"]
