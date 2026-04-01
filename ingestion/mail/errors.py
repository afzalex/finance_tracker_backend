"""Exceptions shared by all mail providers."""


class MailProviderAuthError(Exception):
    """Raised when the configured mail provider requires user authentication."""
