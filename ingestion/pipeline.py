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
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.mail_account import MAIL_PROVIDER_GMAIL, MailAccount
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
    CONFIG_KEY_APP_MAIL_GMAIL_LABELS,
    CONFIG_KEY_APP_MAIL_INITIAL_LOOKBACK_DAYS,
    CONFIG_KEY_APP_MAIL_POLL_SECONDS,
    CONFIG_KEY_INTERNAL_MAIL_GMAIL_HISTORY_ID,
    CONFIG_KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT,
    get_mail_scoped_config_value,
    get_required_config_csv_list,
    get_required_config_csv_list_mail_scoped,
    get_required_config_int,
    insert_fetched_email_raw,
    primary_gmail_mail_config_scope_id,
    reset_fetched_email_enrichment,
    set_email_classification,
    set_enrichment_processing_time_ms,
    upsert_mail_scoped_config_value,
)
from backend.ingestion.parsers import TransactionParser

logger = logging.getLogger(__name__)


class IngestCancelled(Exception):
    """Cooperative stop requested (e.g. admin mail ingest cancel)."""

    def __init__(self, stats: dict) -> None:
        self.stats = stats
        super().__init__("ingest cancelled")


def _ingest_cancel_requested(args: argparse.Namespace) -> bool:
    ev = getattr(args, "cancel_event", None)
    return ev is not None and ev.is_set()

def _gmail_token_present_in_db() -> bool:
    try:
        with SessionLocal() as db:
            for row in db.scalars(
                select(MailAccount).where(
                    MailAccount.provider == MAIL_PROVIDER_GMAIL,
                    MailAccount.is_active.is_(True),
                )
            ).all():
                if (row.token_json or "").strip():
                    return True
    except OperationalError:
        return False
    return False


def _log_gmail_auth_issue(exc: GmailAuthError) -> None:
    credentials_file = settings.gmail_credentials_file

    creds_exists = os.path.exists(credentials_file)
    token_in_db = _gmail_token_present_in_db()

    if not creds_exists:
        logger.error(
            "Mail ingest error: missing Gmail OAuth credentials.\n"
            "The application is not initialized for mail ingestion.\n"
            "Required file: %s\n"
            "Next steps:\n"
            "- Download your OAuth client secret JSON from Google Cloud Console.\n"
            "- Save it to the required path above.\n"
            "- Then authenticate via the app (or CLI) to store a token in mail_accounts.\n"
            "Details: %s",
            credentials_file,
            exc,
        )
        return

    if not token_in_db:
        logger.warning(
            "Mail ingest warning: Gmail is not authenticated yet (no token in mail_accounts).\n"
            "Credentials file found: %s\n"
            "Next steps (frontend-triggered OAuth flow):\n"
            "- Start: POST /api/v1/admin/mail/gmail/token/start?redirect_uri=<callback>\n"
            "- Finish: GET  /api/v1/admin/mail/gmail/token/callback?state=...&code=...\n"
            "Details: %s",
            credentials_file,
            "No valid Gmail token found.",
        )
        return

    logger.warning(
        "Mail ingest warning: Gmail authentication failed.\n"
        "Credentials file: %s\n"
        "You may need to re-authenticate (OAuth) to refresh mail_accounts token data.\n"
        "Details: %s",
        credentials_file,
        exc,
    )


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


def mail_force_ingest_args(
    *,
    lookback_days: int,
    max_messages: int | None = None,
) -> argparse.Namespace:
    """Args for ``ingest --force`` over a custom lookback window (same as CLI ``--force``).

    ``lookback_days`` overrides ``app.mail.initial_lookback_days`` for this run only.
    ``max_messages``, when set, caps how many newest messages in that window are processed.
    """
    return argparse.Namespace(
        command="ingest",
        mail=True,
        unparsed=False,
        offline=False,
        poll=False,
        once=None,
        force=-1 if max_messages is None else max_messages,
        lookback_days=lookback_days,
        limit=None,
        only_mail_id=None,
    )


def run_ingest(args: argparse.Namespace) -> dict | None:
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
            return None
        if getattr(args, "offline", False):
            _ingest_offline(db, limit=getattr(args, "limit", None))
            return None
        if getattr(args, "unparsed", False):
            _ingest_from_unparsed(db, limit=getattr(args, "limit", None))
            return None
        return _ingest_from_gmail(db, args)


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

    with SessionLocal() as db:
        poll_seconds = get_required_config_int(db, CONFIG_KEY_APP_MAIL_POLL_SECONDS, min_value=1)
    logger.info(
        "Poll daemon started — interval: %ss (mail=%s unparsed=%s offline=%s)",
        poll_seconds,
        tick.mail,
        tick.unparsed,
        tick.offline,
    )
    while not _stop:
        try:
            run_ingest(tick)
        except GmailAuthError as exc:
            _log_gmail_auth_issue(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("Ingest error during poll: %s", exc)

        with SessionLocal() as db:
            poll_seconds = get_required_config_int(db, CONFIG_KEY_APP_MAIL_POLL_SECONDS, min_value=1)
        for _ in range(poll_seconds):
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

def _ingest_from_gmail(db: Session, args: argparse.Namespace) -> dict:
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
        _log_gmail_auth_issue(exc)
        raise

    once_n: Optional[int] = getattr(args, "once", None)
    force_arg: Optional[int] = getattr(args, "force", None)

    mail_scope_id = primary_gmail_mail_config_scope_id(db)
    label_names = get_required_config_csv_list_mail_scoped(
        db, CONFIG_KEY_APP_MAIL_GMAIL_LABELS, mail_scope_id
    )

    classifier = MessageClassifier(db)
    parser = TransactionParser(db)
    classifier.load_rules()
    parser.load_parsers()
    stats = dict(fetched=0, parsed=0, unparsed=0, skipped=0, duplicate=0)

    if once_n is not None:
        query = _gmail_label_query(label_names)
        stubs_iter = client.iter_message_stubs(query=query, max_results=once_n)
    elif force_arg is not None:
        max_in_window = None if force_arg < 0 else force_arg
        lookback_override = getattr(args, "lookback_days", None)
        stubs_iter = _fetch_full(
            client,
            max_results=max_in_window,
            mail_scope_id=mail_scope_id,
            lookback_days=lookback_override,
        )
    else:
        history_id = get_mail_scoped_config_value(
            db, CONFIG_KEY_INTERNAL_MAIL_GMAIL_HISTORY_ID, mail_scope_id
        )

        if history_id:
            entries = _gmail_history_label_entries(client, label_names)
            if not entries:
                logger.warning(
                    "No Gmail labels resolved for history sync — falling back to full fetch (lookback window)"
                )
                stubs_iter = _fetch_full(client, mail_scope_id=mail_scope_id)
            else:
                try:
                    stubs_iter = _iter_history_for_label_ids(
                        client, history_id, entries
                    )
                except HistoryExpiredError:
                    logger.warning("History ID expired — falling back to full fetch")
                    stubs_iter = _fetch_full(client, mail_scope_id=mail_scope_id)
        else:
            stubs_iter = _fetch_full(client, mail_scope_id=mail_scope_id)

    for stub in stubs_iter:
        if _ingest_cancel_requested(args):
            _log_ingest_summary(stats)
            raise IngestCancelled(stats)
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
        _save_cursor(db, client, mail_scope_id)

    _log_ingest_summary(stats)
    return stats


def _fetch_full(
    client: GmailClient,
    *,
    max_results: Optional[int] = None,
    mail_scope_id: int | None = None,
    lookback_days: Optional[int] = None,
) -> Iterator[dict]:
    """Build a lookback query and stream message stubs (newest first within the API order)."""
    with SessionLocal() as db:
        sid = mail_scope_id if mail_scope_id is not None else primary_gmail_mail_config_scope_id(db)
        if lookback_days is None:
            resolved_lookback = get_required_config_int(
                db, CONFIG_KEY_APP_MAIL_INITIAL_LOOKBACK_DAYS, min_value=0
            )
        else:
            resolved_lookback = lookback_days
        labels = get_required_config_csv_list_mail_scoped(
            db, CONFIG_KEY_APP_MAIL_GMAIL_LABELS, sid
        )
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=resolved_lookback)
    label_q = _gmail_label_query(labels)
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

    ``classifier`` / ``parser`` must already have rules loaded (callers typically use
    ``_process_emails`` or ``_ingest_from_gmail``, which load once per batch).

    Ensures a ``fetched_emails`` row exists (insert-only for new ``mail_id``), resets
    and then upserts ``fetched_email_enrichments`` for this processing pass.
    """
    stats["fetched"] += 1
    if settings.log_level == "DEBUG":
        logger.debug(
            "Processing mail mail_id=%s subject=%r sender=%r",
            email.mail_id,
            (email.subject or "")[:200],
            (email.sender or "")[:120],
        )
    else:
        logger.info("Processing mail mail_id=%s", email.mail_id)

    t0 = time.perf_counter()
    completed = False
    try:
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
    classifier.load_rules()
    parser.load_parsers()

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


def _save_cursor(db: Session, client: GmailClient, mail_scope_id: int) -> None:
    """Persist the current Gmail ``historyId`` so the next run can do an incremental sync."""
    profile = client.get_profile()
    history_id = str(profile.get("historyId", ""))
    upsert_mail_scoped_config_value(
        db, CONFIG_KEY_INTERNAL_MAIL_GMAIL_HISTORY_ID, history_id or None, mail_scope_id
    )
    upsert_mail_scoped_config_value(
        db,
        CONFIG_KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT,
        datetime.now(tz=timezone.utc).isoformat(),
        mail_scope_id,
    )
    commit_with_retry(db)
    logger.debug("Saved ingest cursor historyId=%s", history_id)


# ── Display helpers ───────────────────────────────────────────────────────────

def _log_ingest_summary(stats: dict) -> None:
    """Log a one-line ingestion summary (CLI / scheduled ingest)."""
    logger.info(
        "Ingestion Summary : fetched: %s  parsed: %s  unparsed: %s  skipped: %s  duplicate: %s",
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
