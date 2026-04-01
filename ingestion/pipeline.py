"""Ingestion pipeline — orchestrates fetch → classify → parse → save.

Entry points
------------
run_ingest(args)   One-shot or --once / --force run.
run_poll(args)     Continuous polling daemon (``poll`` command or ``ingest --poll``).
run_unparsed(args) List / inspect messages from the unparsed queue.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.ingest_cursor import IngestCursor
from backend.app.models.unparsed_message import UnparsedMessage
from backend.config import settings
from backend.database import SessionLocal, commit_with_retry
from backend.ingestion.classifier import MessageClassifier
from backend.ingestion.extraction import EmailContent, extract_email_content
from backend.ingestion.gmail.auth import GmailAuthError
from backend.ingestion.gmail.client import GmailClient, HistoryExpiredError
from backend.ingestion.handlers import dispatch
from backend.ingestion.handlers.context import HandlerContext
from backend.ingestion.persistence import (
    insert_fetched_email_raw,
    reset_fetched_email_enrichment,
    set_email_classification,
    set_enrichment_processing_time_ms,
)
from backend.ingestion.parsers import TransactionParser

logger = logging.getLogger(__name__)


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


def _gmail_history_label_entries(
    client: GmailClient, label_names: list[str]
) -> list[tuple[str, str]]:
    """Resolve user label names to Gmail label ids; log missing names once."""
    entries: list[tuple[str, str]] = []
    missing: list[str] = []
    for name in label_names:
        lid = client.get_label_id(name)
        if lid is None:
            missing.append(name)
        else:
            entries.append((name, lid))
    if missing:
        logger.warning(
            "Gmail label(s) not found; skipped for history sync (fix ``GMAIL_LABEL`` / ``gmail_label``): %s",
            ", ".join(missing),
        )
    return entries


def _iter_history_for_label_ids(
    client: GmailClient, history_id: str, label_entries: list[tuple[str, str]]
) -> Iterator[dict]:
    """Merge ``history.list`` across labels (one ``labelId`` per call); dedupe by message id."""
    seen: set[str] = set()
    for _name, lid in label_entries:
        for stub in client.iter_history_message_stubs(
            start_history_id=history_id, label_id=lid
        ):
            mid = stub.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                yield stub


def _iter_history_for_labels(
    client: GmailClient, history_id: str, label_names: list[str]
) -> Iterator[dict]:
    """Merge history across configured labels (used by tests and thin wrappers)."""
    entries = _gmail_history_label_entries(client, label_names)
    yield from _iter_history_for_label_ids(client, history_id, entries)


# ── Public entry points ────────────────────────────────────────────────────────

def _ingest_args_for_poll_tick(base: argparse.Namespace) -> argparse.Namespace:
    """Build args for a single ingest inside the poll loop (no ``--poll`` / ``--once`` / ``--force``)."""
    return argparse.Namespace(
        once=None,
        force=None,
        only_mail_id=None,
        poll=False,
        mail=bool(getattr(base, "mail", True)),
        unparsed=bool(getattr(base, "unparsed", False)),
        offline=bool(getattr(base, "offline", False)),
        limit=None,
    )


def incremental_mail_ingest_tick_args() -> argparse.Namespace:
    """Args for one incremental remote-mail ingest tick (same shape as a default ``poll`` tick).

    The active provider is implementation-defined (Gmail today); this only selects the
    ``--mail`` code path and default poll flags.
    """
    return _ingest_args_for_poll_tick(
        argparse.Namespace(mail=True, unparsed=False, offline=False)
    )


def run_ingest(args: argparse.Namespace) -> None:
    """Main ingest pipeline entry point.

    Dispatches to one of three fetch modes based on CLI flags:
    - ``--poll``     → start ``run_poll`` with the same source flags (Gmail / unparsed / offline).
    - ``--offline``  → re-process emails already stored in ``fetched_emails`` (optional ``--limit``).
    - ``--unparsed`` → re-process the current ``unparsed_messages`` queue (optional ``--limit``).
    - (default)      → fetch from Gmail (incremental, ``--once``, or ``--force``).
    """
    if getattr(args, "poll", False):
        run_poll(args)
        return

    with SessionLocal() as db:
        if getattr(args, "only_mail_id", None):
            _ingest_one_from_fetched(db, str(getattr(args, "only_mail_id")))
        elif getattr(args, "offline", False):
            _ingest_offline(db, limit=getattr(args, "limit", None))
        elif getattr(args, "unparsed", False):
            _ingest_from_unparsed(db, limit=getattr(args, "limit", None))
        else:
            _ingest_from_gmail(db, args)


def run_poll(base_args: Optional[argparse.Namespace] = None) -> None:
    """Continuous polling daemon with graceful SIGTERM / SIGINT shutdown.

    Each tick runs one ``run_ingest`` using ``base_args`` source flags (``--mail`` /
    ``--unparsed`` / ``--offline``). ``--once`` / ``--force`` apply only to the
    standalone ``ingest`` command, not between poll intervals.
    """
    _stop = False

    def _handler(sig, frame):  # noqa: ANN001
        nonlocal _stop
        logger.info("Stopping poll daemon…")
        _stop = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

    base = base_args if base_args is not None else argparse.Namespace(
        mail=True,
        unparsed=False,
        offline=False,
    )
    tick = _ingest_args_for_poll_tick(base)

    logger.info(
        "Poll daemon started — interval: %ss (mail=%s unparsed=%s offline=%s)",
        settings.poll_seconds,
        tick.mail,
        tick.unparsed,
        tick.offline,
    )
    while not _stop:
        try:
            run_ingest(tick)
        except GmailAuthError as exc:
            logger.error("Auth error: %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Ingest error during poll: %s", exc)

        for _ in range(settings.poll_seconds):
            if _stop:
                break
            time.sleep(1)

    logger.info("Poll daemon stopped.")


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
    except GmailAuthError:
        logger.warning("Gmail client auth failed", exc_info=True)
        raise

    once_n: Optional[int] = getattr(args, "once", None)
    force_arg: Optional[int] = getattr(args, "force", None)

    classifier = MessageClassifier(db)
    parser = TransactionParser(db)
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
            entries = _gmail_history_label_entries(client, settings.gmail_labels)
            if not entries:
                logger.warning(
                    "No Gmail labels resolved for history sync — falling back to full fetch (lookback window)"
                )
                stubs_iter = _fetch_full(client)
            else:
                try:
                    stubs_iter = _iter_history_for_label_ids(
                        client, history_id, entries
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
        commit_with_retry(db)

    if once_n is None:
        _save_cursor(db, client)

    _log_ingest_summary(stats)


def _fetch_full(
    client: GmailClient, *, max_results: Optional[int] = None
) -> Iterator[dict]:
    """Build a lookback query and stream message stubs (newest first within the API order)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=settings.initial_lookback_days)
    label_q = _gmail_label_query(settings.gmail_labels)
    query = f"{label_q} after:{cutoff.year}/{cutoff.month}/{cutoff.day}"
    return client.iter_message_stubs(query=query, max_results=max_results)


# ── Offline / re-process modes ────────────────────────────────────────────────

def _ingest_offline(db: Session, limit: Optional[int] = None) -> None:
    """Re-classify and re-parse emails already stored in fetched_emails.

    ``limit`` (if positive) caps how many rows are processed, oldest first.
    """
    q = db.query(FetchedEmail).order_by(FetchedEmail.internal_date_ms.asc())
    if limit is not None:
        if limit <= 0:
            _log_ingest_summary(
                dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)
            )
            return
        q = q.limit(limit)
    rows = q.all()
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
    _log_ingest_summary(stats)

def reprocess_all_from_fetched(db: Session) -> dict:
    """Re-classify and re-parse all cached emails from ``fetched_emails`` (offline mode)."""
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
    return _process_emails(emails, db)

def reprocess_one_from_fetched(db: Session, mail_id: str) -> dict:
    """Re-classify and re-parse one stored fetched email by provider ``mail_id``.

    Returns the same stats dict produced by ``_process_emails``.
    """
    row = db.query(FetchedEmail).filter(FetchedEmail.mail_id == mail_id).one_or_none()
    if row is None:
        raise KeyError(mail_id)
    email = EmailContent(
        mail_id=row.mail_id,
        thread_id=row.thread_id or "",
        subject=row.subject or "",
        sender=row.sender or "",
        snippet=row.snippet or "",
        internal_date_ms=row.internal_date_ms,
        body_text=row.body_text or "",
        fetched_email_id=row.id,
    )
    return _process_emails([email], db)


def _ingest_one_from_fetched(db: Session, mail_id: str) -> None:
    """CLI wrapper: re-process one cached email and print stats; exit 1 if missing."""
    try:
        stats = reprocess_one_from_fetched(db, mail_id)
    except KeyError:
        logger.error("No fetched_emails row for mail_id %r", mail_id)
        _log_ingest_summary(dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0))
        raise SystemExit(1)
    _log_ingest_summary(stats)


def _ingest_from_unparsed(db: Session, limit: Optional[int] = None) -> None:
    """Re-classify and re-parse messages currently in the unparsed queue.

    ``limit`` (if positive) caps how many queue rows are processed, oldest first.
    """
    q = db.query(UnparsedMessage).order_by(UnparsedMessage.created_at.asc())
    if limit is not None:
        if limit <= 0:
            _log_ingest_summary(
                dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)
            )
            return
        q = q.limit(limit)
    rows = q.all()
    if not rows:
        _log_ingest_summary(dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0))
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
    _log_ingest_summary(stats)


# ── Core processing loop ───────────────────────────────────────────────────────


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
    if settings.log_level == "DEBUG":
        logger.debug(
            "Parsing mail mail_id=%s subject=%r sender=%r",
            email.mail_id,
            (email.subject or "")[:200],
            (email.sender or "")[:120],
        )
    else:
        logger.info("Parsing mail mail_id=%s", email.mail_id)

    t0 = time.perf_counter()
    completed = False
    try:
        classifier.load_rules()
        parser.load_parsers()
        insert_fetched_email_raw(db, email)
        assert email.fetched_email_id is not None
        reset_fetched_email_enrichment(db, email.fetched_email_id)

        result = classifier.classify(
            email.sender, email.subject, email.body_text, email.snippet
        )

        set_email_classification(
            db,
            email.fetched_email_id,
            result.message_type,
            classification_id=result.classification_id,
            classification_reason=result.classification_reason,
        )

        ctx = HandlerContext(
            db=db,
            email=email,
            result=result,
            parser=parser,
            stats=stats,
        )
        dispatch(ctx)
        completed = True
    finally:
        fe_id = getattr(email, "fetched_email_id", None)
        if fe_id is not None and completed:
            elapsed_ms = max(0, int(round((time.perf_counter() - t0) * 1000)))
            set_enrichment_processing_time_ms(db, fe_id, elapsed_ms)


def _process_emails(
    emails: list[EmailContent],
    db: Session,
) -> dict:
    """Classify and dispatch each message to a type-specific handler.

    For each message: upsert raw cache row if needed, refresh enrichment, then
    classify and run the registered handler (transaction parse, sink, unparsed, …).
    """
    classifier = MessageClassifier(db)
    parser = TransactionParser(db)

    stats = dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)

    total = len(emails)
    for i, email in enumerate(emails, start=1):
        _process_one_email(
            email=email,
            db=db,
            classifier=classifier,
            parser=parser,
            stats=stats,
        )
        commit_with_retry(db)
        if total > 100 and i % 200 == 0:
            logger.info("Batch ingest progress: %d / %d messages", i, total)

    return stats


# ── Gmail cursor ───────────────────────────────────────────────────────────────


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
    commit_with_retry(db)
    logger.debug("Saved ingest cursor historyId=%s", history_id)


# ── Display helpers ───────────────────────────────────────────────────────────

def _log_ingest_summary(stats: dict) -> None:
    """Log a one-line ingestion summary (CLI / scheduled ingest)."""
    logger.info(
        "Done — fetched: %s  parsed: %s  unparsed: %s  skipped: %s  duplicate: %s",
        stats["fetched"],
        stats["parsed"],
        stats["unparsed"],
        stats["skipped"],
        stats["duplicate"],
    )


def _list_unparsed(db: Session) -> None:
    """Log the 50 most recent unparsed messages in tabular form."""
    rows = (
        db.query(UnparsedMessage)
        .order_by(UnparsedMessage.created_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        logger.info("No unparsed messages.")
        return
    logger.info(f"{'ID':<6}  {'Mail ID':<24}  {'Reason':<40}  {'Created'}")
    logger.info("-" * 90)
    fe_ids = [r.fetched_email_id for r in rows]
    fe_map = {
        f.id: f.mail_id
        for f in db.query(FetchedEmail).filter(FetchedEmail.id.in_(fe_ids)).all()
    }
    for r in rows:
        created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        mid = fe_map.get(r.fetched_email_id, "?")
        logger.info("%s", f"{r.id:<6}  {mid:<24}  {(r.reason or ''):<40}  {created}")


def _show_unparsed(db: Session, mail_id: str) -> None:
    """Log full details for a single unparsed message, including its raw body (first 2000 chars)."""
    fe = db.execute(
        select(FetchedEmail).where(FetchedEmail.mail_id == mail_id)
    ).scalar_one_or_none()
    if fe is None:
        logger.info("No fetched email with mail_id %r", mail_id)
        return
    row = (
        db.query(UnparsedMessage)
        .filter(UnparsedMessage.fetched_email_id == fe.id)
        .first()
    )
    if not row:
        logger.info("No unparsed message for mail_id %r", mail_id)
        return

    logger.info("Mail ID    : %s", fe.mail_id)
    logger.info("Reason     : %s", row.reason)
    logger.info("Classifier : %s", row.classification_id)
    logger.info("Parser     : %s", row.parser_id)
    logger.info("Created    : %s", row.created_at)
    logger.info("Sender     : %s", fe.sender)
    logger.info("Subject    : %s", fe.subject)
    logger.info("Snippet    : %s", fe.snippet)
    logger.info("Body:\n%s", (fe.body_text or "")[:2000])
