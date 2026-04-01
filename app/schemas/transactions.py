"""Transaction list/read schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .enums import AccountType, Direction, Status, SubType, TransactionType


class TransactionBase(BaseModel):
    """Core transaction fields shared by request and response schemas."""

    provider: Optional[str] = None
    account_id: Optional[str] = None
    account_last4: Optional[str] = None
    card_last4: Optional[str] = None
    card_network: Optional[str] = None
    card_brand: Optional[str] = None
    amount: Optional[str] = None
    amount_parsed: float
    currency: str = "INR"
    direction: Direction
    merchant: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_vpa: Optional[str] = None
    counterparty_account: Optional[str] = None
    counterparty_number: Optional[str] = None
    counterparty_id: Optional[str] = None
    category: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    sub_type: Optional[SubType] = None
    account_type: Optional[AccountType] = None
    status: Optional[Status] = None
    txn_id: Optional[str] = None
    fee_amount: Optional[float] = None
    balance: Optional[float] = None
    reward_points: Optional[float] = None
    parser_id: Optional[int] = None
    classification_id: Optional[int] = None
    transacted_at: datetime


class TransactionRead(TransactionBase):
    """Full transaction response including DB-assigned ``id`` and audit fields."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    mail_id: str
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated wrapper returned by ``GET /api/v1/transactions``."""

    items: list[TransactionRead]
    total: int
    page: int
    page_size: int
