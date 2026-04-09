from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.exclusion_rule import ExclusionRule
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.schemas.exclusion_rules import (
    ExclusionRuleCreate,
    ExclusionRuleRead,
    ExclusionRuleUpdate,
)
from backend.database import get_db

router = APIRouter()


import json

def _payees_to_json(payees: list[str] | None) -> str | None:
    if payees is None:
        return None
    return json.dumps(payees)

def _json_to_payees(json_str: str | None) -> list[str]:
    if not json_str:
        return []
    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return [str(s) for s in data]
        return []
    except Exception:
        return []

def _parser_ids_to_csv(ids: list[int] | None) -> str | None:
    """Convert API ``list[int]`` → DB comma-separated string."""
    if not ids:
        return None
    return ",".join(str(i) for i in sorted(set(ids)))


def _csv_to_parser_ids(csv: str | None) -> list[int]:
    """Convert DB comma-separated string → API ``list[int]``."""
    if not csv or not csv.strip():
        return []
    parts = [p.strip() for p in csv.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            continue
    return sorted(set(out))


def _read(row: ExclusionRule, *, mail_count: int = 0) -> ExclusionRuleRead:
    return ExclusionRuleRead(
        id=row.id,
        name=row.name,
        payees=_json_to_payees(row.payees),
        parser_ids=_csv_to_parser_ids(row.parser_ids),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        mail_count=mail_count,
    )


def _exclusion_enrichment_count(db: Session, exclusion_rule_id: int) -> int:
    n = db.scalar(
        select(func.count())
        .select_from(FetchedEmailEnrichment)
        .where(FetchedEmailEnrichment.exclusion_rule_id == exclusion_rule_id)
    )
    return int(n or 0)


@router.get("", response_model=list[ExclusionRuleRead], summary="List Exclusion Rules")
def list_exclusion_rules(db: Session = Depends(get_db)):
    """Return all exclusion rules (newest first) with mail counts."""
    mail_count_expr = func.count(FetchedEmailEnrichment.fetched_email_id)
    stmt = (
        select(ExclusionRule, mail_count_expr)
        .outerjoin(
            FetchedEmailEnrichment,
            FetchedEmailEnrichment.exclusion_rule_id == ExclusionRule.id,
        )
        .group_by(ExclusionRule)
        .order_by(ExclusionRule.id.desc())
    )
    return [
        _read(row, mail_count=int(n or 0))
        for row, n in db.execute(stmt).all()
    ]


@router.post("", response_model=ExclusionRuleRead, summary="Create Exclusion Rule")
def create_exclusion_rule(payload: ExclusionRuleCreate, db: Session = Depends(get_db)):
    """Create a new rule to exclude matching transactions from financial models."""
    data = payload.model_dump()
    data["parser_ids"] = _parser_ids_to_csv(data.get("parser_ids"))
    if "payees" in data:
        data["payees"] = _payees_to_json(data["payees"])
    rule = ExclusionRule(**data)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _read(rule, mail_count=0)


@router.patch("/{rule_id}", response_model=ExclusionRuleRead, summary="Update Exclusion Rule")
def update_exclusion_rule(
    payload: ExclusionRuleUpdate,
    rule_id: int = Path(...),
    db: Session = Depends(get_db),
):
    """Update properties of an existing exclusion rule."""
    rule = db.get(ExclusionRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "parser_ids" in update_data:
        update_data["parser_ids"] = _parser_ids_to_csv(update_data["parser_ids"])
    if "payees" in update_data:
        update_data["payees"] = _payees_to_json(update_data["payees"])
    for key, value in update_data.items():
        setattr(rule, key, value)

    db.commit()
    db.refresh(rule)
    return _read(rule, mail_count=_exclusion_enrichment_count(db, rule.id))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Exclusion Rule")
def delete_exclusion_rule(rule_id: int = Path(...), db: Session = Depends(get_db)):
    """Permanently delete an exclusion rule."""
    rule = db.get(ExclusionRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    db.delete(rule)
    db.commit()
