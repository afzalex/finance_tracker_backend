"""FastAPI application factory for the Finance Tracker backend."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from backend.app.exception_handlers import emails_request_validation_handler
from backend.app.routers import accounts, analytics, emails, stats, transactions


def create_app() -> FastAPI:
    """Create, configure, and return the FastAPI application instance.

    Registers all API routers under ``/api/v1`` and adds CORS middleware
    permitting read-only access from local frontend dev servers.
    """
    app = FastAPI(
        title="Finance Tracker API",
        version="2.0.0",
        description=(
            "Read-only REST API that surfaces financial data collected by the CLI ingestion tool. "
            "All writes are performed exclusively by the CLI."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_exception_handler(RequestValidationError, emails_request_validation_handler)

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
    app.include_router(
        emails.router,
        prefix="/api/v1/emails",
        tags=["Emails"],
    )
    app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"])
    app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
    app.include_router(stats.router, prefix="/api/v1/stats", tags=["Stats"])

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        """Liveness check — returns ``{"status": "ok"}`` when the server is running."""
        return {"status": "ok"}

    return app


app = create_app()
