"""Accounts router — per-account activity and channel breakdown."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from backend.app.schemas import AccountRead
from backend.database import get_db

router = APIRouter()


@router.get("", response_model=list[AccountRead])
async def list_accounts(db: Session = Depends(get_db)) -> list[AccountRead]:
    """Return all known accounts/cards/wallets.

    TODO: Implement in AccountService.
    """
    raise NotImplementedError


@router.get("/{account_id}/transactions")
async def account_transactions(
    account_id: str = Path(...),
    db: Session = Depends(get_db),
) -> dict:
    """Return transaction history for a specific account.

    TODO: Implement in AccountService.
    """
    raise NotImplementedError
