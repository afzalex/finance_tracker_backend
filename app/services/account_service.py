"""Account list derived from transaction aggregates."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.account import Account
from backend.app.models.transaction import Direction, Transaction
from backend.app.services.transaction_service import _day_end, _day_start
from backend.app.schemas.accounts import (
    AccountFromTransactionsMergedRead,
    AccountTransactionsConflictEntry,
    AccountUpsert,
    AccountUpsertRead,
)


def _norm_at(v: Optional[str]) -> Optional[str]:
    s = (v or "").strip()
    return s if s else None


def list_accounts_from_transactions(
    db: Session,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[AccountFromTransactionsMergedRead]:
    """Group transactions by ``account_id`` (merged), with sums, counts, and optional ``_conflict``."""
    stmt = select(
        Transaction.provider,
        Transaction.account_id,
        Transaction.account_type,
        Transaction.direction,
        func.sum(Transaction.amount_parsed).label("amount_sum"),
        func.count().label("cnt"),
    ).where(
        Transaction.provider.isnot(None),
        Transaction.account_id.isnot(None),
        Transaction.provider != "",
        Transaction.account_id != "",
    )
    if date_from is not None:
        stmt = stmt.where(Transaction.transacted_at >= _day_start(date_from))
    if date_to is not None:
        stmt = stmt.where(Transaction.transacted_at <= _day_end(date_to))
    stmt = stmt.group_by(
        Transaction.provider,
        Transaction.account_id,
        Transaction.account_type,
        Transaction.direction,
    )
    rows = db.execute(stmt).all()

    by_account: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_account[r.account_id].append(r)

    out: list[AccountFromTransactionsMergedRead] = []
    for account_id in sorted(by_account.keys()):
        slices = by_account[account_id]
        credit_amount = 0.0
        debit_amount = 0.0
        credit_count = 0
        debit_count = 0
        for s in slices:
            amt = float(s.amount_sum or 0.0)
            c = int(s.cnt or 0)
            if s.direction == Direction.CREDIT:
                credit_amount += amt
                credit_count += c
            else:
                debit_amount += amt
                debit_count += c
        count = credit_count + debit_count
        net_amount = credit_amount - debit_amount

        # One conflict row per distinct (provider, account_type) within this account_id
        conflict_acc: dict[tuple[str, Optional[str]], dict[str, float | int]] = defaultdict(
            lambda: {
                "credit_amount": 0.0,
                "debit_amount": 0.0,
                "credit_count": 0,
                "debit_count": 0,
                "count": 0,
            }
        )
        for s in slices:
            at = _norm_at(s.account_type)
            key = (s.provider, at)
            bucket = conflict_acc[key]
            amt = float(s.amount_sum or 0.0)
            c = int(s.cnt or 0)
            if s.direction == Direction.CREDIT:
                bucket["credit_amount"] = float(bucket["credit_amount"]) + amt
                bucket["credit_count"] = int(bucket["credit_count"]) + c
            else:
                bucket["debit_amount"] = float(bucket["debit_amount"]) + amt
                bucket["debit_count"] = int(bucket["debit_count"]) + c
            bucket["count"] = int(bucket["count"]) + c

        conflict_list: Optional[list[AccountTransactionsConflictEntry]] = None
        if len(conflict_acc) > 1:
            conflict_list = [
                AccountTransactionsConflictEntry(
                    provider=p,
                    account_type=at,
                    credit_amount=float(v["credit_amount"]),
                    debit_amount=float(v["debit_amount"]),
                    credit_count=int(v["credit_count"]),
                    debit_count=int(v["debit_count"]),
                    count=int(v["count"]),
                )
                for (p, at), v in sorted(
                    conflict_acc.items(),
                    key=lambda item: (item[0][0], item[0][1] or ""),
                )
            ]

        # Winning (provider, account_type): slice with highest transaction count; tie-break lexicographic
        best_key = max(
            conflict_acc.keys(),
            key=lambda k: (
                int(conflict_acc[k]["count"]),
                k[0],
                k[1] or "",
            ),
        )
        win_provider, win_at = best_key[0], best_key[1]

        display_name: Optional[str] = None
        public_id: Optional[int] = None
        account_type_out: Optional[str] = win_at
        provider_out = win_provider

        acc_row = db.scalar(
            select(Account).where(
                Account.provider == win_provider,
                Account.account_id == account_id,
            )
        )
        if acc_row is not None:
            public_id = acc_row.id
            if str(acc_row.provider).strip():
                provider_out = str(acc_row.provider).strip()
            if acc_row.display_name is not None and str(acc_row.display_name).strip():
                display_name = str(acc_row.display_name).strip()
            if acc_row.account_type is not None and str(acc_row.account_type).strip():
                account_type_out = str(acc_row.account_type).strip()

        out.append(
            AccountFromTransactionsMergedRead(
                account_id=account_id,
                provider=provider_out,
                account_type=account_type_out,
                credit_amount=credit_amount,
                debit_amount=debit_amount,
                amount=net_amount,
                credit_count=credit_count,
                debit_count=debit_count,
                count=count,
                display_name=display_name,
                id=public_id,
                conflict=conflict_list,
            )
        )
    return out


def upsert_account(db: Session, body: AccountUpsert) -> AccountUpsertRead:
    """Insert or update ``accounts`` for ``(provider, account_id)``."""
    prov = body.provider.strip()
    aid = body.account_id.strip()
    patch = body.model_dump(exclude_unset=True)
    row = db.scalar(
        select(Account).where(
            Account.provider == prov,
            Account.account_id == aid,
        )
    )
    if row is None:
        row = Account(
            provider=prov,
            account_id=aid,
            display_name=patch.get("display_name"),
            account_type=patch.get("account_type"),
        )
        db.add(row)
    else:
        if "display_name" in patch:
            row.display_name = patch["display_name"]
        if "account_type" in patch:
            row.account_type = patch["account_type"]
    db.commit()
    db.refresh(row)
    return AccountUpsertRead.model_validate(row)
