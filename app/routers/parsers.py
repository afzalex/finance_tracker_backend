"""Parser rules — CRUD on ``parsers`` (delete is a soft deactivate)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.parser import Parser
from backend.app.schemas import (
    AccountType,
    ParserCreate,
    ParserRead,
    ParserUpdate,
    Status,
    SubType,
    TransactionType,
)
from backend.database import get_db

router = APIRouter()


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _clamp_priority(value: int) -> int:
    # Backward-compat: existing DB rows may have 0.
    return max(1, min(100, int(value)))

def _read(row: Parser) -> ParserRead:
    def _upper(v: str | None) -> str | None:
        return v.upper() if isinstance(v, str) else None

    def _enum_or_none(enum_cls, v: str | None):
        if v is None:
            return None
        try:
            return enum_cls(_upper(v))
        except Exception:
            return None

    def _status(v: str | None):
        if v is None:
            return None
        try:
            return Status(_upper(v))
        except Exception:
            return Status.UNKNOWN

    data = {
        "id": row.id,
        "name": row.name,
        "label": row.label,
        "priority": _clamp_priority(row.priority),
        "sender_match_regex": row.sender_match_regex,
        "subject_match_regex": row.subject_match_regex,
        "body_match_regex": row.body_match_regex,
        "subject_extract_regex": row.subject_extract_regex,
        "body_extract_regex": row.body_extract_regex,
        "snippet_extract_regex": row.snippet_extract_regex,
        "txn_date_fmt": row.txn_date_fmt,
        "txn_time_fmt": row.txn_time_fmt,
        "provider": _upper(row.provider),
        "account_type": _enum_or_none(AccountType, row.account_type),
        "transaction_type": _enum_or_none(TransactionType, row.transaction_type),
        "sub_type": _enum_or_none(SubType, row.sub_type),
        "status": _status(row.status),
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    return ParserRead.model_validate(data)


@router.get("", response_model=list[ParserRead])
async def list_parsers(db: Session = Depends(get_db)) -> list[ParserRead]:
    """Return all parser rules, highest ``priority`` first (same order as ``TransactionParser``)."""
    stmt = select(Parser).order_by(Parser.priority.desc(), Parser.id)
    rows = db.scalars(stmt).all()
    return [_read(r) for r in rows]


@router.post(
    "",
    response_model=ParserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a parser rule",
)
async def create_parser(
    body: ParserCreate,
    db: Session = Depends(get_db),
) -> ParserRead:
    """Insert a new parser. Ingest uses only rows with ``is_active`` true."""
    now = _utc_naive_now()
    row = Parser(
        name=body.name,
        label=body.label,
        priority=body.priority,
        sender_match_regex=body.sender_match_regex,
        subject_match_regex=body.subject_match_regex,
        body_match_regex=body.body_match_regex,
        subject_extract_regex=body.subject_extract_regex,
        body_extract_regex=body.body_extract_regex,
        snippet_extract_regex=body.snippet_extract_regex,
        txn_date_fmt=body.txn_date_fmt,
        txn_time_fmt=body.txn_time_fmt,
        provider=body.provider,
        account_type=str(getattr(body.account_type, "value", body.account_type)) if body.account_type is not None else None,
        transaction_type=str(getattr(body.transaction_type, "value", body.transaction_type)) if body.transaction_type is not None else None,
        sub_type=str(getattr(body.sub_type, "value", body.sub_type)) if body.sub_type is not None else None,
        status=str(getattr(body.status, "value", body.status)) if body.status is not None else None,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _read(row)


@router.patch(
    "/{parser_id}",
    response_model=ParserRead,
    summary="Update a parser rule",
)
async def patch_parser(
    parser_id: int = Path(..., ge=1),
    body: ParserUpdate = ...,
    db: Session = Depends(get_db),
) -> ParserRead:
    """Apply a partial update. Omitted JSON fields are left unchanged."""
    row = db.get(Parser, parser_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parser not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        return ParserRead.model_validate(row)

    for key, value in data.items():
        if key in {"account_type", "transaction_type", "sub_type", "status"} and value is not None:
            value = str(getattr(value, "value", value))
        setattr(row, key, value)
    row.updated_at = _utc_naive_now()
    db.commit()
    db.refresh(row)
    return _read(row)


@router.delete(
    "/{parser_id}",
    response_model=ParserRead,
    summary="Deactivate a parser rule",
)
async def delete_parser(
    parser_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
) -> ParserRead:
    """Set ``is_active`` to false — the row is not removed. Idempotent if already inactive."""
    row = db.get(Parser, parser_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parser not found")
    if row.is_active:
        row.is_active = False
        row.updated_at = _utc_naive_now()
        db.commit()
        db.refresh(row)
    return _read(row)
