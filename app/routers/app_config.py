"""Runtime DB-backed app config (``app_config``).

Only keys in the ``app.*`` namespace are updatable via this API.
Keys in ``internal.*`` are read-only runtime state (cursors, timestamps, …).

Gmail ingest uses ``mail_account_id`` (query param) for:

- ``app.mail.gmail.labels``
- ``internal.mail.gmail.history_id``
- ``internal.mail.ingest.last_run_at``

Use ``mail_account_id=0`` for system-wide defaults; use a ``mail_accounts.id`` for
per-mailbox labels and cursors (must match the primary Gmail account used for ingest).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.app_config import APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID, AppConfig
from backend.app.schemas import AppConfigRead, AppConfigUpdate
from backend.database import get_db

router = APIRouter()


def _is_updatable_key(key: str) -> bool:
    return key.startswith("app.")


@router.get("", response_model=list[AppConfigRead])
def list_app_config(
    include_internal: bool = Query(default=False, description="Include read-only internal.* keys."),
    mail_account_id: int = Query(
        default=APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID,
        ge=0,
        description="``0`` lists system-wide rows; use a ``mail_accounts.id`` for per-mailbox config.",
    ),
    db: Session = Depends(get_db),
) -> list[AppConfigRead]:
    stmt = (
        select(AppConfig)
        .where(AppConfig.mail_account_id == mail_account_id)
        .order_by(AppConfig.key.asc())
    )
    rows = db.execute(stmt).scalars().all()
    out: list[AppConfigRead] = []
    for r in rows:
        if not include_internal and not _is_updatable_key(r.key):
            continue
        out.append(
            AppConfigRead(
                id=r.id,
                mail_account_id=r.mail_account_id,
                key=r.key,
                value=r.value,
                updated_at=r.updated_at,
                is_updatable=_is_updatable_key(r.key),
            )
        )
    return out


@router.patch("/{key}", response_model=AppConfigRead)
def update_app_config(
    payload: AppConfigUpdate,
    key: str = Path(..., description="Config key (must start with app.)"),
    mail_account_id: int = Query(
        default=APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID,
        ge=0,
        description="``0`` updates system-wide config; otherwise scopes to that ``mail_accounts.id``.",
    ),
    db: Session = Depends(get_db),
) -> AppConfigRead:
    if key.startswith("internal."):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal.* keys are read-only")
    if not _is_updatable_key(key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only app.* keys are updatable")

    row = db.scalars(
        select(AppConfig).where(
            AppConfig.mail_account_id == mail_account_id,
            AppConfig.key == key,
        )
    ).first()
    if row is None:
        row = AppConfig(mail_account_id=mail_account_id, key=key, value=payload.value)
        db.add(row)
    else:
        row.value = payload.value
    db.commit()
    db.refresh(row)
    return AppConfigRead(
        id=row.id,
        mail_account_id=row.mail_account_id,
        key=row.key,
        value=row.value,
        updated_at=row.updated_at,
        is_updatable=True,
    )

