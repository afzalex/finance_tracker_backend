"""Read queries joining ``fetched_emails`` with transactions and enrichment."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.transaction import Transaction


def list_top_emails_with_transaction_and_enrichment(
    db: Session,
    *,
    limit: int,
) -> list[tuple[FetchedEmail, FetchedEmailEnrichment, datetime, int]]:
    """Rows with enrichment + ≥1 transaction, ordered by latest ``transacted_at`` desc.

    Returns tuples ``(email, enrichment, last_transacted_at, transaction_count)``.
    """
    per_mail = (
        select(
            Transaction.mail_id.label("mail_id"),
            func.max(Transaction.transacted_at).label("last_at"),
            func.count().label("txn_count"),
        )
        .group_by(Transaction.mail_id)
        .subquery()
    )

    stmt = (
        select(FetchedEmail, FetchedEmailEnrichment, per_mail.c.last_at, per_mail.c.txn_count)
        .join(FetchedEmailEnrichment, FetchedEmailEnrichment.fetched_email_id == FetchedEmail.id)
        .join(per_mail, per_mail.c.mail_id == FetchedEmail.mail_id)
        .order_by(per_mail.c.last_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())
