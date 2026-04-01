"""Central configuration for the Finance Tracker backend.

All settings are read from environment variables or a .env file at the project
root.  Import ``settings`` wherever you need config values:

    from backend.config import settings
"""

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/finance.db"

    # ── Gmail ─────────────────────────────────────────────────────────────────
    gmail_credentials_file: str = "secrets/credentials.json"
    gmail_token_file: str = "secrets/token.json"
    gmail_label: str = Field(
        default="Finance",
        description=(
            "Comma-separated Gmail label names (env GMAIL_LABEL). "
            "Do not use commas inside a single label name."
        ),
    )

    @computed_field
    @property
    def gmail_labels(self) -> list[str]:
        parts = [x.strip() for x in self.gmail_label.split(",") if x.strip()]
        return parts if parts else ["Finance"]

    # ── Ingestion ─────────────────────────────────────────────────────────────
    poll_seconds: int = 300
    initial_lookback_days: int = 30
    confidence_threshold: int = 50
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
    env: str = "development"
    api_scheduled_ingest_enabled: bool = Field(
        default=True,
        description=(
            "When True, the FastAPI process runs incremental mail ingest on an interval "
            "(``poll_seconds``). Disable in tests via env ``API_SCHEDULED_INGEST_ENABLED=false``."
        ),
    )


settings = Settings()
