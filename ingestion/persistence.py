"""Persistence helpers for ingestion — fetched emails, enrichments, unparsed queue, transactions."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.app_config import APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID, AppConfig
from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
from backend.app.models.transaction import Transaction
from backend.app.models.unparsed_message import UnparsedMessage
from backend.database import flush_with_retry
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
    flush_with_retry(db)
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
    row.processing_time_ms = None
    flush_with_retry(db)


def set_enrichment_processing_time_ms(
    db: Session, fetched_email_id: int, elapsed_ms: int
) -> None:
    """Record how long the last processing pass took (persisted on the next ``commit``)."""
    row = get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.processing_time_ms = max(0, elapsed_ms)


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
        is_self_transfer=bool(fields.get("is_self_transfer", False)),
        balance=fields.get("balance"),
        reward_points=fields.get("reward_points"),
        parser_id=fields.get("parser_id"),
        classification_id=fields.get("classification_id"),
    )
    try:
        with db.begin_nested():
            db.add(txn)
            flush_with_retry(db)
    except IntegrityError:
        return "duplicate"
    return "inserted"


# ── DB app_config key/value ───────────────────────────────────────────────────
#
# Convention:
# - ``internal.*``: read-only runtime state (not user-updatable via API)
# - ``app.*``: user-updatable runtime config

CONFIG_KEY_INTERNAL_MAIL_GMAIL_HISTORY_ID = "internal.mail.gmail.history_id"
CONFIG_KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT = "internal.mail.ingest.last_run_at"

CONFIG_KEY_APP_MAIL_GMAIL_LABELS = "app.mail.gmail.labels"
CONFIG_KEY_APP_MAIL_POLL_SECONDS = "app.mail.poll_seconds"
CONFIG_KEY_APP_MAIL_INITIAL_LOOKBACK_DAYS = "app.mail.initial_lookback_days"
CONFIG_KEY_APP_INGEST_CONFIDENCE_THRESHOLD = "app.ingest.confidence_threshold"

# Gmail ingest labels + cursors: one row per ``mail_accounts.id`` (use ``0`` only for legacy / system).
MAIL_SCOPED_CONFIG_KEYS = frozenset(
    {
        CONFIG_KEY_APP_MAIL_GMAIL_LABELS,
        CONFIG_KEY_INTERNAL_MAIL_GMAIL_HISTORY_ID,
        CONFIG_KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT,
    }
)


def primary_gmail_mail_config_scope_id(db: Session) -> int:
    """``mail_accounts.id`` for the active primary Gmail row, else ``0`` (system scope)."""
    row = db.scalars(
        select(MailAccount)
        .where(
            MailAccount.provider == MAIL_PROVIDER_GMAIL,
            MailAccount.is_active.is_(True),
        )
        .order_by(MailAccount.is_primary.desc(), MailAccount.id.asc())
        .limit(1)
    ).first()
    if row is not None:
        return row.id
    return APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID


def get_mail_scoped_config_value(db: Session, key: str, scope_id: int) -> Optional[str]:
    """Read config for ``scope_id``, then fall back to system rows (``mail_account_id == 0``)."""
    order = [scope_id]
    if scope_id != APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID:
        order.append(APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID)
    for sid in order:
        raw = get_config_value(db, key, mail_account_id=sid)
        if raw is not None and str(raw).strip():
            return raw
    return None


def get_required_config_csv_list_mail_scoped(db: Session, key: str, scope_id: int) -> list[str]:
    raw = get_mail_scoped_config_value(db, key, scope_id)
    if raw is None or not str(raw).strip():
        raise ValueError(
            f"Missing required app_config key {key!r} for mail_account_id={scope_id} (with system fallback)"
        )
    parts = [p.strip() for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError(f"Invalid CSV list for app_config key {key!r}: {raw!r}")
    return parts


def upsert_mail_scoped_config_value(
    db: Session, key: str, value: Optional[str], scope_id: int
) -> None:
    upsert_config_value(db, key, value, mail_account_id=scope_id)


def _app_config_row(db: Session, key: str, mail_account_id: int) -> Optional[AppConfig]:
    return db.scalars(
        select(AppConfig).where(
            AppConfig.mail_account_id == mail_account_id,
            AppConfig.key == key,
        )
    ).first()


def get_config_value(
    db: Session, key: str, *, mail_account_id: int = APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID
) -> Optional[str]:
    row = _app_config_row(db, key, mail_account_id)
    return None if row is None else row.value


def upsert_config_value(
    db: Session, key: str, value: Optional[str], *, mail_account_id: int = APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID
) -> None:
    row = _app_config_row(db, key, mail_account_id)
    if row is None:
        db.add(AppConfig(mail_account_id=mail_account_id, key=key, value=value))
    else:
        row.value = value


def get_required_config_value(
    db: Session, key: str, *, mail_account_id: int = APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID
) -> str:
    raw = (get_config_value(db, key, mail_account_id=mail_account_id) or "").strip()
    if not raw:
        raise ValueError(f"Missing required app_config key {key!r}")
    return raw


def get_required_config_int(
    db: Session,
    key: str,
    *,
    min_value: Optional[int] = None,
    mail_account_id: int = APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID,
) -> int:
    raw = get_required_config_value(db, key, mail_account_id=mail_account_id)
    try:
        v = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid int for app_config key {key!r}: {raw!r}") from exc
    if min_value is not None:
        v = max(min_value, v)
    return v


def get_required_config_csv_list(
    db: Session, key: str, *, mail_account_id: int = APP_CONFIG_SYSTEM_MAIL_ACCOUNT_ID
) -> list[str]:
    raw = get_required_config_value(db, key, mail_account_id=mail_account_id)
    parts = [p.strip() for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError(f"Invalid CSV list for app_config key {key!r}: {raw!r}")
    return parts
