"""Classifier rules — CRUD on ``classifications`` (delete is a soft deactivate)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.classification import Classification
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.schemas import ClassificationCreate, ClassificationRead, ClassificationUpdate
from backend.database import get_db

router = APIRouter()


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _message_type_value(value) -> str:
    # Schema uses Enum; ORM uses Enum too. Normalize to its string value.
    return str(getattr(value, "value", value))

def _clamp_priority(value: int) -> int:
    # Backward-compat: existing DB rows may have 0. Enforce 1..100 in API.
    return max(1, min(100, int(value)))

def _classification_enrichment_count(db: Session, classification_id: int) -> int:
    n = db.scalar(
        select(func.count())
        .select_from(FetchedEmailEnrichment)
        .where(FetchedEmailEnrichment.classification_id == classification_id)
    )
    return int(n or 0)


def _read(row: Classification, *, mail_count: int = 0) -> ClassificationRead:
    data = {
        "id": row.id,
        "name": row.name,
        "message_type": _message_type_value(row.message_type),
        "priority": _clamp_priority(row.priority),
        "sender_match_regex": row.sender_match_regex,
        "subject_match_regex": row.subject_match_regex,
        "body_match_regex": row.body_match_regex,
        "subject_extract_regex": row.subject_extract_regex,
        "body_extract_regex": row.body_extract_regex,
        "snippet_extract_regex": row.snippet_extract_regex,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "mail_count": mail_count,
    }
    return ClassificationRead.model_validate(data)


@router.get("", response_model=list[ClassificationRead])
async def list_classifications(db: Session = Depends(get_db)) -> list[ClassificationRead]:
    """Return all classification rules, highest ``priority`` first (same order as the classifier)."""
    mail_count_expr = func.count(FetchedEmailEnrichment.fetched_email_id)
    stmt = (
        select(Classification, mail_count_expr)
        .outerjoin(
            FetchedEmailEnrichment,
            FetchedEmailEnrichment.classification_id == Classification.id,
        )
        .group_by(Classification)
        .order_by(Classification.priority.desc(), Classification.id)
    )
    return [
        _read(row, mail_count=int(n or 0))
        for row, n in db.execute(stmt).all()
    ]


@router.post(
    "",
    response_model=ClassificationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a classification rule",
)
async def create_classification(
    body: ClassificationCreate,
    db: Session = Depends(get_db),
) -> ClassificationRead:
    """Insert a new rule. Ingest uses only rows with ``is_active`` true."""
    mt = _message_type_value(body.message_type)
    now = _utc_naive_now()
    row = Classification(
        name=body.name,
        message_type=mt,
        priority=body.priority,
        sender_match_regex=body.sender_match_regex,
        subject_match_regex=body.subject_match_regex,
        body_match_regex=body.body_match_regex,
        subject_extract_regex=body.subject_extract_regex,
        body_extract_regex=body.body_extract_regex,
        snippet_extract_regex=body.snippet_extract_regex,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _read(row, mail_count=0)


@router.patch(
    "/{classification_id}",
    response_model=ClassificationRead,
    summary="Update a classification rule",
)
async def patch_classification(
    classification_id: int = Path(..., ge=1),
    body: ClassificationUpdate = ...,
    db: Session = Depends(get_db),
) -> ClassificationRead:
    """Apply a partial update. Omitted JSON fields are left unchanged."""
    row = db.get(Classification, classification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        return _read(row, mail_count=_classification_enrichment_count(db, row.id))

    if "message_type" in data:
        data["message_type"] = _message_type_value(data["message_type"])

    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = _utc_naive_now()
    db.commit()
    db.refresh(row)
    return _read(row, mail_count=_classification_enrichment_count(db, row.id))


@router.delete(
    "/{classification_id}",
    response_model=ClassificationRead,
    summary="Deactivate a classification rule",
)
async def delete_classification(
    classification_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
) -> ClassificationRead:
    """Set ``is_active`` to false — the row is not removed. Idempotent if already inactive."""
    row = db.get(Classification, classification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification not found")
    if row.is_active:
        row.is_active = False
        row.updated_at = _utc_naive_now()
        db.commit()
        db.refresh(row)
    return _read(row, mail_count=_classification_enrichment_count(db, row.id))
