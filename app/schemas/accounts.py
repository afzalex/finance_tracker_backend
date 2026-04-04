"""Account summary schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AccountRead(BaseModel):
    """Account/card/wallet summary returned by ``GET /api/v1/accounts``."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None


class AccountTransactionsConflictEntry(BaseModel):
    """One ``(provider, account_type)`` slice for the same ``account_id`` in transactions."""

    provider: str
    account_type: Optional[str] = None
    credit_amount: float = Field(..., ge=0)
    debit_amount: float = Field(..., ge=0)
    credit_count: int = Field(..., ge=0)
    debit_count: int = Field(..., ge=0)
    count: int = Field(
        ...,
        ge=0,
        description="Total transaction rows in this slice (``credit_count + debit_count``).",
    )


class AccountFromTransactionsMergedRead(BaseModel):
    """Transactions rolled up by ``account_id``, with optional multi-slice ``_conflict``."""

    model_config = ConfigDict(populate_by_name=True)

    account_id: str
    provider: str
    account_type: Optional[str] = None
    credit_amount: float = Field(..., ge=0)
    debit_amount: float = Field(..., ge=0)
    amount: float = Field(
        ...,
        description="Net of credits minus debits (``credit_amount - debit_amount``) for this ``account_id``.",
    )
    credit_count: int = Field(..., ge=0)
    debit_count: int = Field(..., ge=0)
    count: int = Field(..., ge=0)
    display_name: Optional[str] = Field(
        None, description="From ``accounts`` for the chosen ``(provider, account_id)`` when present."
    )
    id: Optional[int] = Field(
        None,
        description="``accounts.id`` when a row exists for the chosen ``provider`` + ``account_id``.",
    )
    conflict: Optional[list[AccountTransactionsConflictEntry]] = Field(
        default=None,
        serialization_alias="_conflict",
        description="Present when more than one distinct ``(provider, account_type)`` shares this ``account_id``.",
    )


class AccountUpsert(BaseModel):
    """Upsert body for ``PUT /api/v1/accounts`` (keyed by ``provider`` + ``account_id``)."""

    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    display_name: Optional[str] = None
    account_type: Optional[str] = None


class AccountUpsertRead(BaseModel):
    """Row stored in ``accounts`` after upsert."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None
