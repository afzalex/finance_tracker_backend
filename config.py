"""Central configuration for the Finance Tracker backend.

All settings are read from environment variables or a .env file at the project
root.  Import ``settings`` wherever you need config values:

    from backend.config import settings
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/finance.db"

    # ── Gmail (provider implementation settings; not runtime-tunable) ─────────
    gmail_credentials_file: str = "secrets/credentials.json"
    gmail_token_file: str = "secrets/token.json"

    # ── Ingestion ─────────────────────────────────────────────────────────────
    # Note: runtime-tunable ingestion parameters live in DB ``app_config``.
    max_body_extract_chars: int = Field(
        default=131_072,
        ge=0,
        description="Max characters of body used for ``body_extract_regex``; ``0`` = unlimited.",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description=(
            "DEBUG, INFO, WARNING, ERROR, or TRACE. "
            "TRACE enables SQLAlchemy SQL echo; DEBUG does not."
        ),
    )

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description=(
            "Allowed CORS origins. Only needed for local dev where the frontend "
            "dev server runs on a different port than the API. In production the "
            "SPA is served by the same server so this can be left empty."
        ),
    )
    env: str = "development"
    api_scheduled_ingest_enabled: bool = Field(
        default=True,
        description=(
            "When True, the FastAPI process runs incremental mail ingest on an interval "
            "(``poll_seconds``). Disable in tests via env ``API_SCHEDULED_INGEST_ENABLED=false``."
        ),
    )
    api_serve_frontend: bool = Field(
        default=True,
        description=(
            "When True, ``GET /`` serves the placeholder ``index.html`` (or future static frontend). "
            "Set ``API_SERVE_FRONTEND=false`` for API-only deployments behind a separate web server."
        ),
    )


settings = Settings()
