"""Mail ingestion shared across providers (Gmail today; others later)."""

from backend.ingestion.mail.errors import MailProviderAuthError

__all__ = ["MailProviderAuthError"]
