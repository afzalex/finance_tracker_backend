"""FastAPI application factory for the Finance Tracker backend."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.config import settings
from backend.app.exception_handlers import emails_request_validation_handler
from backend.app.lifecycle import scheduled_ingest_lifespan
from backend.app.logging_setup import ensure_backend_stderr_logging
from backend.app.routers import (
    accounts,
    admin,
    analytics,
    app_config,
    classifications,
    emails,
    parsers,
    stats,
    transactions,
)


def create_app(*, serve_frontend: bool | None = None) -> FastAPI:
    """Create, configure, and return the FastAPI application instance.

    Registers all API routers under ``/api/v1`` and adds CORS middleware
    permitting read-only access from local frontend dev servers.

    ``serve_frontend`` overrides ``settings.api_serve_frontend`` (env ``API_SERVE_FRONTEND``)
    for tests; when false, ``GET /`` is not registered.
    """
    ensure_backend_stderr_logging()

    app = FastAPI(
        title="Finance Tracker API",
        version="2.0.0",
        description=(
            "REST API for ledger reads, cached emails, and classifier/parser management. "
            "While the server runs, incremental mail ingest can run on the same interval as "
            "``poll_seconds`` (disable with ``API_SCHEDULED_INGEST_ENABLED=false``). "
            "DELETE on classifications/parsers only sets ``is_active`` false — rows are kept."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=scheduled_ingest_lifespan,
    )

    app.add_exception_handler(RequestValidationError, emails_request_validation_handler)

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
    app.include_router(
        emails.router,
        prefix="/api/v1/emails",
        tags=["Emails"],
    )
    app.include_router(
        classifications.router,
        prefix="/api/v1/classifications",
        tags=["Classifications"],
    )
    app.include_router(
        parsers.router,
        prefix="/api/v1/parsers",
        tags=["Parsers"],
    )
    app.include_router(app_config.router, prefix="/api/v1/app-config", tags=["AppConfig"])
    app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"])
    app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
    app.include_router(stats.router, prefix="/api/v1/stats", tags=["Stats"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        """Liveness check — returns ``{"status": "ok"}`` when the server is running."""
        return {"status": "ok"}

    _serve = settings.api_serve_frontend if serve_frontend is None else serve_frontend
    if _serve:

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            """Placeholder landing page for local dev (to be replaced by frontend)."""
            index_path = Path(__file__).resolve().parents[1] / "index.html"
            return FileResponse(index_path)

    return app


app = create_app()
