"""Account list derived from transaction aggregates."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Literal, Optional

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
    CounterpartyFromTransactionsRead,
    MerchantFromTransactionsRead,
    PartyRollupsRead,
)


def _norm_at(v: Optional[str]) -> Optional[str]:
    s = (v or "").strip()
    return s if s else None


def list_accounts_from_transactions(
    db: Session,
    *,
    from_: Optional[date] = None,
    to: Optional[date] = None,
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
        Transaction.is_excluded.is_(False),
    )
    if from_ is not None:
        stmt = stmt.where(Transaction.transacted_at >= _day_start(from_))
    if to is not None:
        stmt = stmt.where(Transaction.transacted_at <= _day_end(to))
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


def _list_party_summaries_from_transactions(
    db: Session,
    label_column,
    *,
    from_: Optional[date] = None,
    to: Optional[date] = None,
) -> list[tuple[str, float, float, float, int, int, int]]:
    """Group non-excluded rows by trimmed ``label_column``; return sorted summary tuples."""
    trimmed = func.trim(label_column)
    stmt = select(
        trimmed.label("name"),
        Transaction.direction,
        func.sum(Transaction.amount_parsed).label("amount_sum"),
        func.count().label("cnt"),
    ).where(
        label_column.isnot(None),
        trimmed != "",
        Transaction.is_excluded.is_(False),
    )
    if from_ is not None:
        stmt = stmt.where(Transaction.transacted_at >= _day_start(from_))
    if to is not None:
        stmt = stmt.where(Transaction.transacted_at <= _day_end(to))
    stmt = stmt.group_by(trimmed, Transaction.direction)
    rows = db.execute(stmt).all()

    by_name: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "credit_amount": 0.0,
            "debit_amount": 0.0,
            "credit_count": 0,
            "debit_count": 0,
        }
    )
    for r in rows:
        name = str(r.name).strip()
        if not name:
            continue
        bucket = by_name[name]
        amt = float(r.amount_sum or 0.0)
        c = int(r.cnt or 0)
        if r.direction == Direction.CREDIT:
            bucket["credit_amount"] = float(bucket["credit_amount"]) + amt
            bucket["credit_count"] = int(bucket["credit_count"]) + c
        else:
            bucket["debit_amount"] = float(bucket["debit_amount"]) + amt
            bucket["debit_count"] = int(bucket["debit_count"]) + c

    out: list[tuple[str, float, float, float, int, int, int]] = []
    for name in sorted(by_name.keys()):
        b = by_name[name]
        credit_amount = float(b["credit_amount"])
        debit_amount = float(b["debit_amount"])
        credit_count = int(b["credit_count"])
        debit_count = int(b["debit_count"])
        count = credit_count + debit_count
        out.append(
            (
                name,
                credit_amount,
                debit_amount,
                credit_amount - debit_amount,
                credit_count,
                debit_count,
                count,
            )
        )
    return out


def list_merchants_from_transactions(
    db: Session,
    *,
    from_: Optional[date] = None,
    to: Optional[date] = None,
) -> list[MerchantFromTransactionsRead]:
    """Group transactions by ``merchant`` with debit/credit sums and counts."""
    return [
        MerchantFromTransactionsRead(
            merchant=name,
            credit_amount=credit_amount,
            debit_amount=debit_amount,
            amount=net_amount,
            credit_count=credit_count,
            debit_count=debit_count,
            count=count,
        )
        for name, credit_amount, debit_amount, net_amount, credit_count, debit_count, count in _list_party_summaries_from_transactions(
            db,
            Transaction.merchant,
            from_=from_,
            to=to,
        )
    ]


def list_counterparties_from_transactions(
    db: Session,
    *,
    from_: Optional[date] = None,
    to: Optional[date] = None,
) -> list[CounterpartyFromTransactionsRead]:
    """Group transactions by ``counterparty_name`` with debit/credit sums and counts."""
    return [
        CounterpartyFromTransactionsRead(
            counterparty=name,
            credit_amount=credit_amount,
            debit_amount=debit_amount,
            amount=net_amount,
            credit_count=credit_count,
            debit_count=debit_count,
            count=count,
        )
        for name, credit_amount, debit_amount, net_amount, credit_count, debit_count, count in _list_party_summaries_from_transactions(
            db,
            Transaction.counterparty_name,
            from_=from_,
            to=to,
        )
    ]


def list_party_rollups_from_transactions(
    db: Session,
    *,
    from_: Optional[date] = None,
    to: Optional[date] = None,
    kind: Literal["merchant", "counterparty"] | None = None,
) -> PartyRollupsRead:
    """Return merchant and/or counterparty rollups; ``kind`` limits to one dimension."""
    merchants: list[MerchantFromTransactionsRead] = []
    counterparties: list[CounterpartyFromTransactionsRead] = []
    if kind is None or kind == "merchant":
        merchants = list_merchants_from_transactions(
            db, from_=from_, to=to
        )
    if kind is None or kind == "counterparty":
        counterparties = list_counterparties_from_transactions(
            db, from_=from_, to=to
        )
    return PartyRollupsRead(merchants=merchants, counterparties=counterparties)


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
