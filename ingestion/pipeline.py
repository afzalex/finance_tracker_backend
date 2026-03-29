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

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
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


def _gmail_label_term(name: str) -> str:
    """Build one ``label:…`` search atom for Gmail ``messages.list`` query ``q``."""
    n = name.strip()
    if not n:
        return ""
    if any(c in n for c in ' "\t'):
        escaped = n.replace("\\", "\\\\").replace('"', '\\"')
        return f'label:"{escaped}"'
    return f"label:{n}"


def _gmail_label_query(labels: list[str]) -> str:
    """Gmail search fragment: one ``label:`` term or ``(a OR b OR …)`` for several labels."""
    terms = [_gmail_label_term(x) for x in labels]
    terms = [t for t in terms if t]
    if not terms:
        return _gmail_label_term("Finance")
    if len(terms) == 1:
        return terms[0]
    return "(" + " OR ".join(terms) + ")"


def _iter_history_for_labels(
    client: GmailClient, history_id: str, label_names: list[str]
) -> Iterator[dict]:
    """Merge ``history.list`` across labels (API allows one ``labelId`` per call); dedupe by message id."""
    seen: set[str] = set()
    for name in label_names:
        lid = client.get_label_id(name)
        if lid is None:
            logger.warning("Gmail label %r not found; skipping for history sync", name)
            continue
        for stub in client.iter_history_message_stubs(
            start_history_id=history_id, label_id=lid
        ):
            mid = stub.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                yield stub


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
            _args = argparse.Namespace(once=None, force=None, mail=True,
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
    - ``--once N``  Fetch the N most recent messages matching configured label(s); ingest cursor not updated.
    - ``--force``   Ignore the stored cursor and re-fetch the lookback window (optional ``N`` caps messages).
    - (default)     Incremental fetch via Gmail history API from the stored cursor,
                    falling back to a full fetch if the history ID has expired.

    After all messages are processed, the Gmail ingest cursor is saved once (not for
    ``--once``); each message is still committed to the DB as it is processed.
    """
    try:
        client = GmailClient()
    except GmailAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    once_n: Optional[int] = getattr(args, "once", None)
    force_arg: Optional[int] = getattr(args, "force", None)

    classifier = MessageClassifier(db)
    classifier.load_rules()
    parser = TransactionParser(db)
    parser.load_parsers()
    stats = dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)

    if once_n is not None:
        query = _gmail_label_query(settings.gmail_labels)
        stubs_iter = client.iter_message_stubs(query=query, max_results=once_n)
    elif force_arg is not None:
        max_in_window = None if force_arg < 0 else force_arg
        stubs_iter = _fetch_full(client, max_results=max_in_window)
    else:
        cursor = db.query(IngestCursor).first()
        history_id = cursor.gmail_history_id if cursor else None

        if history_id:
            try:
                stubs_iter = _iter_history_for_labels(
                    client, history_id, settings.gmail_labels
                )
            except HistoryExpiredError:
                logger.warning("History ID expired — falling back to full fetch")
                stubs_iter = _fetch_full(client)
        else:
            stubs_iter = _fetch_full(client)

    for stub in stubs_iter:
        msg = client.get_message(stub["id"])
        email = extract_email_content(msg)
        _process_one_email(
            email=email,
            db=db,
            classifier=classifier,
            parser=parser,
            stats=stats,
        )
        db.commit()

    if once_n is None:
        _save_cursor(db, client)

    _print_stats(stats)


def _fetch_full(
    client: GmailClient, *, max_results: Optional[int] = None
) -> Iterator[dict]:
    """Build a lookback query and stream message stubs (newest first within the API order)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=settings.initial_lookback_days)
    label_q = _gmail_label_query(settings.gmail_labels)
    query = f"{label_q} after:{cutoff.year}/{cutoff.month}/{cutoff.day}"
    return client.iter_message_stubs(query=query, max_results=max_results)


# ── Offline / re-process modes ────────────────────────────────────────────────

def _ingest_offline(db: Session) -> None:
    """Re-classify and re-parse all emails already stored in fetched_emails."""
    rows = db.query(FetchedEmail).order_by(FetchedEmail.internal_date_ms.asc()).all()
    emails = [
        EmailContent(
            mail_id=r.mail_id,
            thread_id=r.thread_id or "",
            subject=r.subject or "",
            sender=r.sender or "",
            snippet=r.snippet or "",
            internal_date_ms=r.internal_date_ms,
            body_text=r.body_text or "",
            fetched_email_id=r.id,
        )
        for r in rows
    ]
    stats = _process_emails(emails, db)
    _print_stats(stats)


def _ingest_from_unparsed(db: Session) -> None:
    """Re-classify and re-parse messages currently in the unparsed queue."""
    rows = db.query(UnparsedMessage).order_by(UnparsedMessage.created_at.asc()).all()
    if not rows:
        _print_stats(dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0))
        return
    fe_ids = [u.fetched_email_id for u in rows]
    fetched_map = {
        f.id: f
        for f in db.query(FetchedEmail).filter(FetchedEmail.id.in_(fe_ids)).all()
    }
    emails: list[EmailContent] = []
    for u in rows:
        r = fetched_map.get(u.fetched_email_id)
        if r is None:
            logger.warning(
                "UnparsedMessage id=%s references missing fetched_email_id=%s",
                u.id,
                u.fetched_email_id,
            )
            continue
        emails.append(
            EmailContent(
                mail_id=r.mail_id,
                thread_id=r.thread_id or "",
                subject=r.subject or "",
                sender=r.sender or "",
                snippet=r.snippet or "",
                internal_date_ms=r.internal_date_ms,
                body_text=r.body_text or "",
                fetched_email_id=r.id,
            )
        )
    stats = _process_emails(emails, db)
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
    stats: dict,
) -> None:
    """Process a single message; does not commit.

    Ensures a ``fetched_emails`` row exists (insert-only for new ``mail_id``), resets
    and then upserts ``fetched_email_enrichments`` for this processing pass.
    """
    stats["fetched"] += 1

    _insert_fetched_email_raw(db, email)
    assert email.fetched_email_id is not None
    _reset_fetched_email_enrichment(db, email.fetched_email_id)

    result = classifier.classify(
        email.sender, email.subject, email.body_text, email.snippet
    )

    _set_email_classification(
        db,
        email.fetched_email_id,
        result.message_type,
        classification_id=result.classification_id,
        classification_reason=result.classification_reason,
    )

    if result.message_type == "SINK":
        stats["skipped"] += 1
        # Enrichment already holds classification_id / classification / classification_reason.
        _remove_unparsed(db, email.fetched_email_id)
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

    _set_email_parser_id(db, email.fetched_email_id, parse_result.parser_id)

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

        fields["mail_id"] = email.mail_id
        saved = _upsert_transaction(db, fields)
        if saved == "duplicate":
            stats["duplicate"] += 1
            _remove_unparsed(db, email.fetched_email_id)
        else:
            stats["parsed"] += 1
            _remove_unparsed(db, email.fetched_email_id)
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
) -> dict:
    """Classify, parse, and persist a list of emails.

    For each message: upsert raw cache row if needed, refresh enrichment, then
    classify / parse / persist transactions or unparsed rows.
    """
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
            stats=stats,
        )

    db.commit()
    return stats


# ── DB helpers ────────────────────────────────────────────────────────────────

def _insert_fetched_email_raw(db: Session, email: EmailContent) -> None:
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


def _get_or_create_fetched_email_enrichment(
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


def _reset_fetched_email_enrichment(db: Session, fetched_email_id: int) -> None:
    """Clear enrichment for this run (insert row if missing)."""
    row = _get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.classification_id = None
    row.classification = None
    row.classification_reason = None
    row.parser_id = None
    db.flush()


def _set_email_classification(
    db: Session,
    fetched_email_id: int,
    message_type: str,
    *,
    classification_id: Optional[int],
    classification_reason: Optional[str] = None,
) -> None:
    """Write the classifier result to ``fetched_email_enrichments``."""
    row = _get_or_create_fetched_email_enrichment(db, fetched_email_id)
    row.classification = message_type
    row.classification_id = classification_id
    row.classification_reason = classification_reason


def _set_email_parser_id(db: Session, fetched_email_id: int, parser_id: Optional[int]) -> None:
    """Write the chosen parser id (even when parsing later fails)."""
    row = _get_or_create_fetched_email_enrichment(db, fetched_email_id)
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
        db.add(UnparsedMessage(
            fetched_email_id=fe_id,
            reason=reason,
            classification_id=classification_id,
            parser_id=parser_id,
        ))


def _remove_unparsed(db: Session, fetched_email_id: Optional[int]) -> None:
    """Delete any ``UnparsedMessage`` row for the given fetched email id.

    Called after a previously-failed message is successfully re-parsed, so
    the unparsed queue stays tidy.
    """
    if fetched_email_id is None:
        return
    db.query(UnparsedMessage).filter(
        UnparsedMessage.fetched_email_id == fetched_email_id
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
        # Savepoint rollback only — keeps fetched_email / enrichment / unparsed in the outer txn.
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
    print(f"{'ID':<6}  {'Mail ID':<24}  {'Reason':<40}  {'Created'}")
    print("-" * 90)
    fe_ids = [r.fetched_email_id for r in rows]
    fe_map = {
        f.id: f.mail_id
        for f in db.query(FetchedEmail).filter(FetchedEmail.id.in_(fe_ids)).all()
    }
    for r in rows:
        created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        mid = fe_map.get(r.fetched_email_id, "?")
        print(f"{r.id:<6}  {mid:<24}  {(r.reason or ''):<40}  {created}")


def _show_unparsed(db: Session, mail_id: str) -> None:
    """Print full details for a single unparsed message, including its raw body (first 2000 chars)."""
    fe = db.execute(
        select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)
    ).scalar_one_or_none()
    if fe is None:
        print(f"No fetched email with mail_id {mail_id!r}")
        return
    row = (
        db.query(UnparsedMessage)
        .filter(UnparsedMessage.fetched_email_id == fe.id)
        .first()
    )
    if not row:
        print(f"No unparsed message for mail_id {mail_id!r}")
        return

    print(f"Mail ID    : {fe.mail_id}")
    print(f"Reason     : {row.reason}")
    print(f"Classifier : {row.classification_id}")
    print(f"Parser     : {row.parser_id}")
    print(f"Created    : {row.created_at}")
    print(f"Sender     : {fe.sender}")
    print(f"Subject    : {fe.subject}")
    print(f"Snippet    : {fe.snippet}")
    print()
    print("Body:")
    print((fe.body_text or "")[:2000])
