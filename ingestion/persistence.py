"""Persistence helpers for ingestion — fetched emails, enrichments, unparsed queue, transactions."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.transaction import Transaction
from backend.app.models.unparsed_message import UnparsedMessage
from backend.ingestion.extraction import EmailContent

logger = logging.getLogger(__name__)


def insert_fetched_email_raw(db: Session, email: EmailContent) -> None:
    """Insert raw payload once per ``mail_id``; never update existing rows."""
    existing = db.execute(
        select(FetchedEmail).where(FetchedEmail.mail_id == email.mail_id)
    ).scalar_one_or_none()
    if existing is not None:
        email.fetched_email_id = existing.id
        return
    row = FetchedEmail(
        mail_id=email.mail_id,
        thread_id=email.thread_id,
        subject=email.subject,
        sender=email.sender,
        snippet=email.snippet,
        internal_date_ms=email.internal_date_ms,
        body_text=email.body_text,
    )
    db.add(row)
    db.flush()
    email.fetched_email_id = row.id


def get_or_create_fetched_email_enrichment(
    db: Session, fetched_email_id: int
) -> FetchedEmailEnrichment:
    """Return the 1:1 enrichment row, creating a placeholder if missing."""
    row = db.get(FetchedEmailEnrichment, fetched_email_id)
    if row is None:
        row = FetchedEmailEnrichment(
            fetched_email_id=fetched_email_id,
            classification_id=None,
            classification=None,
            classification_reason=None,
            parser_id=None,
        )
        db.add(row)
    return row


def reset_fetched_email_enrichment(db: Session, fetched_email_id: int) -> None:
    """Clear enrichment for this run (insert row if missing)."""
    row = get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.classification_id = None
    row.classification = None
    row.classification_reason = None
    row.parser_id = None
    db.flush()


def set_email_classification(
    db: Session,
    fetched_email_id: int,
    message_type: str,
    *,
    classification_id: Optional[int],
    classification_reason: Optional[str] = None,
) -> None:
    """Write the classifier result to ``fetched_email_enrichments``."""
    row = get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.classification = message_type
    row.classification_id = classification_id
    row.classification_reason = classification_reason


def set_email_parser_id(db: Session, fetched_email_id: int, parser_id: Optional[int]) -> None:
    """Write the chosen parser id (even when parsing later fails)."""
    row = get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.parser_id = parser_id


def upsert_unparsed(
    db: Session,
    email: EmailContent,
    *,
    reason: Optional[str] = None,
    classification_id: Optional[int] = None,
    parser_id: Optional[int] = None,
) -> None:
    """Record an email as unparsed, updating the existing row if one is already present."""
    if email.fetched_email_id is None:
        logger.warning(
            "Cannot persist unparsed row without fetched_email_id (mail_id=%r)",
            email.mail_id,
        )
        return
    fe_id = email.fetched_email_id
    existing = (
        db.query(UnparsedMessage)
        .filter(UnparsedMessage.fetched_email_id == fe_id)
        .first()
    )
    if existing:
        existing.reason = reason
        existing.classification_id = classification_id
        existing.parser_id = parser_id
    else:
        db.add(
            UnparsedMessage(
                fetched_email_id=fe_id,
                reason=reason,
                classification_id=classification_id,
                parser_id=parser_id,
            )
        )


def remove_unparsed(db: Session, fetched_email_id: Optional[int]) -> None:
    """Delete any ``UnparsedMessage`` row for the given fetched email id."""
    if fetched_email_id is None:
        return
    db.query(UnparsedMessage).filter(
        UnparsedMessage.fetched_email_id == fetched_email_id
    ).delete(synchronize_session=False)


def delete_transactions_for_mail_id(db: Session, mail_id: str) -> int:
    """Remove ledger rows tied to this source message so a re-parse can insert fresh rows.

    Called before processing a ``TRANSACTION_ALERT`` so offline re-ingest or rule changes
    do not leave stale duplicates alongside ``(provider, txn_id)`` deduplication.
    """
    deleted = (
        db.query(Transaction)
        .filter(Transaction.mail_id == mail_id)
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def upsert_transaction(db: Session, fields: dict) -> str:
    """Insert a transaction; skip if (provider, txn_id) already exists.

    Returns 'inserted' or 'duplicate'.
    """
    provider = fields.get("provider")
    txn_id = fields.get("txn_id")

    if provider and txn_id:
        exists = db.query(Transaction).filter(
            Transaction.provider == provider,
            Transaction.txn_id == txn_id,
        ).first()
        if exists:
            return "duplicate"

    txn = Transaction(
        mail_id=fields["mail_id"],
        transacted_at=fields["transacted_at"],
        origin=fields["origin"],
        amount=fields.get("amount"),
        amount_parsed=fields["amount_parsed"],
        currency=fields.get("currency", "INR"),
        direction=fields["direction"],
        provider=provider,
        account_type=fields.get("account_type"),
        account_id=fields.get("account_id"),
        account_last4=fields.get("account_last4"),
        card_last4=fields.get("card_last4"),
        card_network=fields.get("card_network"),
        card_brand=fields.get("card_brand"),
        transaction_type=fields.get("transaction_type"),
        sub_type=fields.get("sub_type"),
        status=fields.get("status"),
        txn_id=txn_id,
        fee_amount=fields.get("fee_amount"),
        merchant=fields.get("merchant"),
        counterparty_name=fields.get("counterparty_name"),
        counterparty_vpa=fields.get("counterparty_vpa"),
        counterparty_account=fields.get("counterparty_account"),
        counterparty_number=fields.get("counterparty_number"),
        counterparty_id=fields.get("counterparty_id"),
        category=fields.get("category"),
        balance=fields.get("balance"),
        reward_points=fields.get("reward_points"),
        parser_id=fields.get("parser_id"),
        classification_id=fields.get("classification_id"),
    )
    try:
        with db.begin_nested():
            db.add(txn)
            db.flush()
    except IntegrityError:
        return "duplicate"
    return "inserted"
