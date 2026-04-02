"""Runtime DB-backed app config (``app_config``).

Only keys in the ``app.*`` namespace are updatable via this API.
Keys in ``internal.*`` are read-only runtime state (cursors, timestamps, …).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.app_config import AppConfig
from backend.app.schemas import AppConfigRead, AppConfigUpdate
from backend.database import get_db

router = APIRouter()


def _is_updatable_key(key: str) -> bool:
    return key.startswith("app.")


@router.get("", response_model=list[AppConfigRead])
def list_app_config(
    include_internal: bool = Query(default=False, description="Include read-only internal.* keys."),
    db: Session = Depends(get_db),
) -> list[AppConfigRead]:
    rows = db.execute(select(AppConfig).order_by(AppConfig.key.asc())).scalars().all()
    out: list[AppConfigRead] = []
    for r in rows:
        if not include_internal and not _is_updatable_key(r.key):
            continue
        out.append(
            AppConfigRead(
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
    db: Session = Depends(get_db),
) -> AppConfigRead:
    if key.startswith("internal."):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal.* keys are read-only")
    if not _is_updatable_key(key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only app.* keys are updatable")

    row = db.get(AppConfig, key)
    if row is None:
        row = AppConfig(key=key, value=payload.value)
        db.add(row)
    else:
        row.value = payload.value
    db.commit()
    db.refresh(row)
    return AppConfigRead(key=row.key, value=row.value, updated_at=row.updated_at, is_updatable=True)

