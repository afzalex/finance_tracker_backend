from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AppMetadataRead(BaseModel):
    """High-level application status for the frontend."""

    app_version: str
    is_healthy: bool
    is_initialized: bool
    is_mail_connectivity_working: bool
    mail_user_email: Optional[str] = None
    mail_user_name: Optional[str] = None
    openapi_url: str
    docs_url: str
    redoc_url: str

