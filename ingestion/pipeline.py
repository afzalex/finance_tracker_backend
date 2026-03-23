"""Ingestion pipeline — orchestrates fetch → classify → parse → save.

Entry points
------------
run_ingest(args)   One-shot or --once / --force run.
run_poll()         Continuous polling daemon.
run_unparsed(args) List / inspect messages from the unparsed queue.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.ingest_cursor import IngestCursor
from backend.app.models.transaction import Transaction
from backend.app.models.unparsed_message import UnparsedMessage
from backend.config import settings
from backend.database import SessionLocal
from backend.ingestion.classifier import MessageClassifier
from backend.ingestion.extraction import EmailContent, extract_email_content
from backend.ingestion.gmail.auth import GmailAuthError
from backend.ingestion.gmail.client import GmailClient, HistoryExpiredError
from backend.ingestion.parsers import TransactionParser

logger = logging.getLogger(__name__)

_PARSEABLE_TYPES = {"TRANSACTION_ALERT"}


# ── Public entry points ────────────────────────────────────────────────────────

def run_ingest(args: argparse.Namespace) -> None:
    """Main ingest pipeline entry point.

    Dispatches to one of three fetch modes based on CLI flags:
    - ``--offline``  → re-process emails already stored in ``fetched_emails``.
    - ``--unparsed`` → re-process the current ``unparsed_messages`` queue.
    - (default)      → fetch from Gmail (incremental, ``--once``, or ``--force``).
    """
    with SessionLocal() as db:
        if getattr(args, "offline", False):
            _ingest_offline(db) # ingest from fetched_emails table
        elif getattr(args, "unparsed", False):
            _ingest_from_unparsed(db) # ingest from unparsed_messages table
        else:
            _ingest_from_gmail(db, args) # ingest from gmail


def run_poll() -> None:
    """Continuous polling daemon with graceful SIGTERM shutdown."""
    _stop = False

    def _handler(sig, frame):  # noqa: ANN001
        nonlocal _stop
        print("\nStopping poll daemon…", flush=True)
        _stop = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

    print(f"Poll daemon started — interval: {settings.poll_seconds}s")
    while not _stop:
        try:
            _args = argparse.Namespace(once=None, force=False, mail=True,
                                       unparsed=False, offline=False)
            run_ingest(_args)
        except GmailAuthError as exc:
            print(f"Auth error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001
            logger.error("Ingest error during poll: %s", exc)

        for _ in range(settings.poll_seconds):
            if _stop:
                break
            time.sleep(1)

    print("Poll daemon stopped.")


def run_unparsed(args: argparse.Namespace) -> None:
    """List or inspect messages from the unparsed queue."""
    with SessionLocal() as db:
        if getattr(args, "show", None):
            _show_unparsed(db, args.show)
        else:
            _list_unparsed(db)


# ── Gmail fetch modes ──────────────────────────────────────────────────────────

def _ingest_from_gmail(db: Session, args: argparse.Namespace) -> None:
    """Fetch emails from Gmail and run the processing pipeline.

    Supports three sub-modes:
    - ``--once N``  Fetch the N most recent labelled messages; cursor not updated.
    - ``--force``   Ignore the stored cursor and re-fetch the full lookback window.
    - (default)     Incremental fetch via Gmail history API from the stored cursor,
                    falling back to a full fetch if the history ID has expired.
    """
    try:
        client = GmailClient()
    except GmailAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    once_n: Optional[int] = getattr(args, "once", None)
    force: bool = getattr(args, "force", False)

    classifier = MessageClassifier(db)
    classifier.load_rules()
    parser = TransactionParser(db)
    parser.load_parsers()
    stats = dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)

    if once_n is not None:
        # --once N: fetch N most recent messages, do NOT update cursor
        query = f"label:{settings.gmail_label}"
        for stub in client.iter_message_stubs(query=query, max_results=once_n):
            msg = client.get_message(stub["id"])
            email = extract_email_content(msg)
            _process_one_email(
                email=email,
                db=db,
                classifier=classifier,
                parser=parser,
                store_emails=True,
                stats=stats,
            )
            db.commit()

        _print_stats(stats)
        return

    if force:
        # --force: ignore cursor, fetch full lookback window
        stubs_iter = _fetch_full(client)
    else:
        # Default: incremental via history, or full fetch if no cursor
        cursor = db.query(IngestCursor).first()
        history_id = cursor.gmail_history_id if cursor else None

        if history_id:
            try:
                label_id = client.get_label_id(settings.gmail_label)
                stubs_iter = client.iter_history_message_stubs(
                    start_history_id=history_id, label_id=label_id
                )
            except HistoryExpiredError:
                logger.warning("History ID expired — falling back to full fetch")
                stubs_iter = _fetch_full(client)
        else:
            stubs_iter = _fetch_full(client)

    processed_any = False
    for stub in stubs_iter:
        processed_any = True
        msg = client.get_message(stub["id"])
        email = extract_email_content(msg)
        _process_one_email(
            email=email,
            db=db,
            classifier=classifier,
            parser=parser,
            store_emails=True,
            stats=stats,
        )
        _save_cursor(db, client)  # commits + advances history cursor

    if not processed_any:
        _save_cursor(db, client)

    _print_stats(stats)


def _fetch_full(client: GmailClient) -> Iterator[dict]:
    """Build a lookback query and stream all message stubs."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=settings.initial_lookback_days)
    query = f"label:{settings.gmail_label} after:{cutoff.year}/{cutoff.month}/{cutoff.day}"
    return client.iter_message_stubs(query=query, max_results=None)


# ── Offline / re-process modes ────────────────────────────────────────────────

def _ingest_offline(db: Session) -> None:
    """Re-classify and re-parse all emails already stored in fetched_emails."""
    rows = db.query(FetchedEmail).order_by(FetchedEmail.internal_date_ms.asc()).all()
    emails = [
        EmailContent(
            gmail_message_id=r.gmail_message_id,
            thread_id=r.thread_id or "",
            subject=r.subject or "",
            sender=r.sender or "",
            snippet=r.snippet or "",
            internal_date_ms=r.internal_date_ms,
            body_text=r.body_text or "",
        )
        for r in rows
    ]
    stats = _process_emails(emails, db, store_emails=False)
    _print_stats(stats)


def _ingest_from_unparsed(db: Session) -> None:
    """Re-classify and re-parse messages currently in the unparsed queue."""
    rows = (
        db.query(UnparsedMessage)
        .join(FetchedEmail, FetchedEmail.gmail_message_id == UnparsedMessage.gmail_message_id)
        .order_by(UnparsedMessage.created_at.asc())
        .all()
    )
    gmail_ids = [r.gmail_message_id for r in rows]
    fetched = (
        db.query(FetchedEmail)
        .filter(FetchedEmail.gmail_message_id.in_(gmail_ids))
        .all()
    )
    emails = [
        EmailContent(
            gmail_message_id=r.gmail_message_id,
            thread_id=r.thread_id or "",
            subject=r.subject or "",
            sender=r.sender or "",
            snippet=r.snippet or "",
            internal_date_ms=r.internal_date_ms,
            body_text=r.body_text or "",
        )
        for r in fetched
    ]
    stats = _process_emails(emails, db, store_emails=False)
    _print_stats(stats)


# ── Core processing loop ───────────────────────────────────────────────────────

class _ParserAttemptError(Exception):
    """Raised when a transaction parse attempt fails."""

    def __init__(self, *, failure_reason: str, parser_id: Optional[int]) -> None:
        super().__init__(failure_reason)
        self.failure_reason = failure_reason
        self.parser_id = parser_id


def _process_one_email(
    *,
    email: EmailContent,
    db: Session,
    classifier: MessageClassifier,
    parser: TransactionParser,
    store_emails: bool,
    stats: dict,
) -> None:
    """Process a single message; does not commit."""
    stats["fetched"] += 1

    if store_emails:
        _upsert_fetched_email(db, email)  # overwrite semantics

    result = classifier.classify(
        email.sender, email.subject, email.body_text, email.snippet
    )

    if store_emails:
        _set_email_classification(
            db,
            email.gmail_message_id,
            result.message_type,
            classification_id=result.classification_id,
        )

    if result.message_type == "SINK":
        stats["skipped"] += 1
        return

    if result.message_type not in _PARSEABLE_TYPES:
        _upsert_unparsed(
            db,
            email,
            reason=f"classification:{result.message_type}",
            classification_id=result.classification_id,
            parser_id=None,
        )
        stats["unparsed"] += 1
        return

    parse_result = parser.parse(
        email.sender,
        email.subject,
        email.body_text,
        email.snippet,
        email.internal_date_ms,
        result.message_type,
        result.classification_id,
    )

    if store_emails:
        _set_email_parser_id(db, email.gmail_message_id, parse_result.parser_id)

    try:
        if not parse_result.success:
            raise _ParserAttemptError(
                failure_reason=parse_result.failure_reason or "parse_failed",
                parser_id=parse_result.parser_id,
            )

        fields = parse_result.fields
        confidence = fields.get("confidence", 0)
        if confidence < settings.confidence_threshold:
            raise _ParserAttemptError(
                failure_reason=f"low_confidence:{confidence}",
                parser_id=parse_result.parser_id,
            )

        fields["gmail_message_id"] = email.gmail_message_id
        saved = _upsert_transaction(db, fields)
        if saved == "duplicate":
            stats["duplicate"] += 1
            _remove_unparsed(db, email.gmail_message_id)
        else:
            stats["parsed"] += 1
            _remove_unparsed(db, email.gmail_message_id)
    except _ParserAttemptError as exc:
        _upsert_unparsed(
            db,
            email,
            reason=exc.failure_reason,
            classification_id=result.classification_id,
            parser_id=exc.parser_id,
        )
        stats["unparsed"] += 1


def _process_emails(
    emails: list[EmailContent],
    db: Session,
    *,
    store_emails: bool = True,
) -> dict:
    """Classify, parse, and persist a list of emails."""
    classifier = MessageClassifier(db)
    classifier.load_rules()
    parser = TransactionParser(db)
    parser.load_parsers()

    stats = dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)

    for email in emails:
        _process_one_email(
            email=email,
            db=db,
            classifier=classifier,
            parser=parser,
            store_emails=store_emails,
            stats=stats,
        )

    db.commit()
    return stats


# ── DB helpers ────────────────────────────────────────────────────────────────

def _upsert_fetched_email(db: Session, email: EmailContent) -> None:
    """Insert a new ``FetchedEmail`` row or overwrite enrichment in place."""
    existing = db.get(FetchedEmail, email.gmail_message_id)
    if existing:
        existing.thread_id = email.thread_id
        existing.subject = email.subject
        existing.sender = email.sender
        existing.snippet = email.snippet
        existing.internal_date_ms = email.internal_date_ms
        existing.body_text = email.body_text
        # Overwrite semantics: clear enrichment fields before re-classifying.
        existing.classification = None
        existing.classification_reason = None
        existing.classification_id = None
        existing.parser_id = None
    else:
        db.add(FetchedEmail(
            gmail_message_id=email.gmail_message_id,
            thread_id=email.thread_id,
            subject=email.subject,
            sender=email.sender,
            snippet=email.snippet,
            internal_date_ms=email.internal_date_ms,
            body_text=email.body_text,
            classification=None,
            classification_reason=None,
            classification_id=None,
            parser_id=None,
        ))


def _set_email_classification(
    db: Session,
    gmail_message_id: str,
    message_type: str,
    *,
    classification_id: Optional[int],
) -> None:
    """Write the classifier result back to the stored ``FetchedEmail`` row."""
    row = db.get(FetchedEmail, gmail_message_id)
    if row:
        row.classification = message_type
        row.classification_id = classification_id


def _set_email_parser_id(db: Session, gmail_message_id: str, parser_id: Optional[int]) -> None:
    """Write the chosen parser id (even when parsing later fails)."""
    row = db.get(FetchedEmail, gmail_message_id)
    if row:
        row.parser_id = parser_id


def _upsert_unparsed(
    db: Session,
    email: EmailContent,
    *,
    reason: Optional[str] = None,
    classification_id: Optional[int] = None,
    parser_id: Optional[int] = None,
) -> None:
    """Record an email as unparsed, updating the existing row if one is already present.

    Args:
        reason:            Short string describing why parsing failed, e.g.
                           ``"no_regex_match"``, ``"low_confidence:42"``,
                           ``"classification:STATEMENT"``.
        classification_id: FK to the ``classifications`` row that matched, if any.
        parser_id:         FK to the ``parsers`` row that was attempted, if any.
    """
    existing = (
        db.query(UnparsedMessage)
        .filter(UnparsedMessage.gmail_message_id == email.gmail_message_id)
        .first()
    )
    if existing:
        existing.reason = reason
        existing.classification_id = classification_id
        existing.parser_id = parser_id
    else:
        db.add(UnparsedMessage(
            gmail_message_id=email.gmail_message_id,
            reason=reason,
            classification_id=classification_id,
            parser_id=parser_id,
        ))


def _remove_unparsed(db: Session, gmail_message_id: str) -> None:
    """Delete any ``UnparsedMessage`` row for the given message ID.

    Called after a previously-failed message is successfully re-parsed, so
    the unparsed queue stays tidy.
    """
    db.query(UnparsedMessage).filter(
        UnparsedMessage.gmail_message_id == gmail_message_id
    ).delete(synchronize_session=False)


def _upsert_transaction(db: Session, fields: dict) -> str:
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
        gmail_message_id=fields["gmail_message_id"],
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
        db.add(txn)
        db.flush()
    except IntegrityError:
        db.rollback()
        return "duplicate"
    return "inserted"


def _save_cursor(db: Session, client: GmailClient) -> None:
    """Persist the current Gmail ``historyId`` so the next run can do an incremental sync."""
    profile = client.get_profile()
    history_id = str(profile.get("historyId", ""))
    cursor = db.query(IngestCursor).first()
    if cursor:
        cursor.gmail_history_id = history_id
        cursor.last_run_at = datetime.now(tz=timezone.utc)
    else:
        db.add(IngestCursor(
            gmail_history_id=history_id,
            last_run_at=datetime.now(tz=timezone.utc),
        ))
    db.commit()
    logger.debug("Saved ingest cursor historyId=%s", history_id)


# ── Display helpers ───────────────────────────────────────────────────────────

def _print_stats(stats: dict) -> None:
    """Print a one-line ingestion summary to stdout."""
    print(
        f"Done — fetched: {stats['fetched']}  "
        f"parsed: {stats['parsed']}  "
        f"unparsed: {stats['unparsed']}  "
        f"skipped: {stats['skipped']}  "
        f"duplicate: {stats['duplicate']}"
    )


def _list_unparsed(db: Session) -> None:
    """Print the 50 most recent unparsed messages to stdout in tabular form."""
    rows = (
        db.query(UnparsedMessage)
        .order_by(UnparsedMessage.created_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        print("No unparsed messages.")
        return
    print(f"{'ID':<6}  {'Gmail ID':<24}  {'Reason':<40}  {'Created'}")
    print("-" * 90)
    for r in rows:
        created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        print(f"{r.id:<6}  {r.gmail_message_id:<24}  {(r.reason or ''):<40}  {created}")


def _show_unparsed(db: Session, gmail_message_id: str) -> None:
    """Print full details for a single unparsed message, including its raw body (first 2000 chars)."""
    row = (
        db.query(UnparsedMessage)
        .filter(UnparsedMessage.gmail_message_id == gmail_message_id)
        .first()
    )
    if not row:
        print(f"No unparsed message with id {gmail_message_id!r}")
        return

    email = db.get(FetchedEmail, gmail_message_id)
    print(f"Gmail ID   : {row.gmail_message_id}")
    print(f"Reason     : {row.reason}")
    print(f"Classifier : {row.classification_id}")
    print(f"Parser     : {row.parser_id}")
    print(f"Created    : {row.created_at}")
    if email:
        print(f"Sender     : {email.sender}")
        print(f"Subject    : {email.subject}")
        print(f"Snippet    : {email.snippet}")
        print()
        print("Body:")
        print(email.body_text[:2000])
