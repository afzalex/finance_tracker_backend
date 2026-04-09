from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.mail_account import MailAccount
from backend.app.schemas import MailAccountCreate, MailAccountRead
from backend.database import get_db

router = APIRouter()


@router.post("", response_model=MailAccountRead, summary="Create Mail Account")
def create_mail_account(
    payload: MailAccountCreate,
    db: Session = Depends(get_db),
) -> MailAccountRead:
    """Insert a mail account row (complete OAuth via ``/admin/mail/gmail/token/...``)."""
    row = MailAccount(
        provider=payload.provider,
        account_mail_id=payload.account_mail_id,
        token_json=payload.token_json,
        is_active=payload.is_active,
        is_primary=payload.is_primary,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[MailAccountRead], summary="List Mail Accounts")
def list_mail_accounts(
    db: Session = Depends(get_db),
) -> list[MailAccountRead]:
    """Return all mail accounts (newest first by id)."""
    stmt = select(MailAccount).order_by(MailAccount.id.desc())
    rows = db.execute(stmt).scalars().all()
    return rows
