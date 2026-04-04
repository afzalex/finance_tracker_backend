from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.app.models.app_config import APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID
from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
from backend.app.schemas import AppMetadataRead
from backend.app.version import APP_VERSION
from backend.config import settings
from backend.database import SessionLocal
from backend.ingestion.gmail.client import GmailClient
from backend.ingestion.persistence import primary_gmail_mail_config_scope_id

router = APIRouter()


def _resolve_setting_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    # backend/app/routers/metadata.py -> .../backend/app/routers -> .../backend
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / p


def _gmail_oauth_ready() -> bool:
    """True when OAuth client secret exists and an active Gmail row has stored token JSON."""
    if not _credentials_present():
        return False
    try:
        with SessionLocal() as db:
            for row in db.scalars(
                select(MailAccount).where(
                    MailAccount.provider == MAIL_PROVIDER_GMAIL,
                    MailAccount.is_active.is_(True),
                )
            ).all():
                if (row.token_json or "").strip():
                    return True
    except OperationalError:
        return False
    return False

def _credentials_present() -> bool:
    return _resolve_setting_path(settings.gmail_credentials_file).exists()


def _primary_mail_account_id_for_meta() -> Optional[int]:
    """Primary Gmail ``mail_accounts.id`` for ingest-scoped config, or ``None`` if none."""
    try:
        with SessionLocal() as db:
            sid = primary_gmail_mail_config_scope_id(db)
            return None if sid == APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID else sid
    except OperationalError:
        return None


def _gmail_connectivity_working_sync() -> bool:
    # Best-effort: try to authenticate and call a lightweight endpoint.
    client = GmailClient()
    client.get_profile()
    return True


def _gmail_profile_sync() -> dict:
    client = GmailClient()
    return client.get_profile()


@router.get("/meta", response_model=AppMetadataRead, summary="Get application metadata")
async def get_metadata(request: Request) -> AppMetadataRead:
    credentials_present = _credentials_present()
    is_initialized = _gmail_oauth_ready()
    primary_mail_account_id = _primary_mail_account_id_for_meta()

    is_mail_connectivity_working = False
    mail_user_email = None
    mail_user_name = None
    if is_initialized:
        try:
            # Keep the endpoint responsive even if the network is slow/unavailable.
            profile = await asyncio.wait_for(
                asyncio.to_thread(_gmail_profile_sync),
                timeout=5.0,
            )
            is_mail_connectivity_working = True
            mail_user_email = profile.get("emailAddress")
            if isinstance(mail_user_email, str) and "@" in mail_user_email:
                mail_user_name = mail_user_email.split("@", 1)[0]
        except Exception:
            is_mail_connectivity_working = False

    base = str(request.base_url).rstrip("/")
    openapi_url = base + (request.app.openapi_url or "/openapi.json")
    docs_url = base + (request.app.docs_url or "/docs")
    redoc_url = base + (request.app.redoc_url or "/redoc")
    return AppMetadataRead(
        app_version=APP_VERSION,
        is_healthy=credentials_present,
        is_initialized=is_initialized,
        is_mail_connectivity_working=is_mail_connectivity_working,
        mail_user_email=mail_user_email,
        mail_user_name=mail_user_name,
        primary_mail_account_id=primary_mail_account_id,
        openapi_url=openapi_url,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )

