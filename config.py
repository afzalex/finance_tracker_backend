"""Central configuration for the Finance Tracker backend.

All settings are read from environment variables or a .env file at the project
root.  Import ``settings`` wherever you need config values:

    from backend.config import settings
"""

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

    # ── Ingestion ─────────────────────────────────────────────────────────────
    poll_seconds: int = 300
    initial_lookback_days: int = 30

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    env: str = "development"


settings = Settings()
