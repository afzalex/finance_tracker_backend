"""Ingestion package — email fetch, classification, parsing, and persistence.

This package owns the full pipeline that turns raw bank alert emails into
structured ``Transaction`` rows in the database.  It is intentionally
decoupled from the FastAPI app layer; the only shared dependency is the
SQLAlchemy session supplied by the caller.

Sub-packages and modules
------------------------
gmail/
    Provider-specific transport layer for fetching emails.

    - ``auth.py``   — OAuth2 credential lifecycle (load, refresh, browser
                      flow).  Raises ``GmailAuthError`` with actionable
                      messages when intervention is required.
    - ``client.py`` — ``GmailClient``: paginated message listing,
                      incremental history sync (``get_history``), and
                      ``HistoryExpiredError`` when the history ID has
                      expired.

extraction.py
    Parses raw Gmail API message dicts into ``EmailContent`` dataclasses.
    Handles multipart MIME trees, quoted-printable / base-64 decoding, and
    converts HTML bodies to plain text via BeautifulSoup.

classifier.py
    ``MessageClassifier`` — loads active rows from the ``classifications``
    table and matches each email against sender / subject / body regexes in
    priority order.  Returns a ``ClassificationResult`` with one of:
    ``TRANSACTION_ALERT``, ``INVESTMENT_NOTICE``, ``STATEMENT``, ``SINK``,
    or ``OTHER``.

parsers/__init__.py
    ``TransactionParser`` — loads active rows from the ``parsers`` table and
    tries them in priority order against each ``TRANSACTION_ALERT`` email.
    Named capture groups in ``body_extract_regex`` map directly to
    ``Transaction`` ORM columns.  Computes a confidence score (0–100) based
    on how many high-value fields were extracted.

utils.py
    Shared regex helpers used by the classifier and parser:

    - ``match_regex(pattern, text, *, empty_means_match)`` — returns
      ``True / False / None`` (None when the pattern is empty and
      ``empty_means_match=False``).
    - ``merge_extract_groups(body_m, subject_m, snippet_m)`` — merges named
      groups from three match objects with body > subject > snippet
      precedence.

pipeline.py
    Orchestrates the end-to-end pipeline and exposes the public entry points
    consumed by ``cli.py``:

    - ``run_ingest(args)``   — one-shot ingest (normal, ``--once``,
                               ``--force``, ``--offline``).
    - ``run_poll()``         — continuous daemon loop (SIGTERM-safe).
    - ``run_unparsed(args)`` — inspect / retry failed messages.

Pipeline stages
---------------
1. **Fetch** — ``GmailClient`` retrieves new message IDs from Gmail using
   either incremental history sync (preferred) or a full label query
   (fallback when the history ID has expired or on the first run).

2. **Extract** — ``extract_email_content()`` decodes each raw message into
   an ``EmailContent`` dataclass.

3. **Store** — the raw email is upserted into ``fetched_emails`` so it can
   be replayed offline (``--offline``) or re-inspected later.

4. **Classify** — ``MessageClassifier.classify()`` determines the email's
   ``MessageType``.  ``SINK`` emails are discarded immediately.  Non-alert
   types are stored in ``unparsed_messages`` with a reason.

5. **Parse** — ``TransactionParser.parse()`` tries each active parser row
   against the email body in priority order.  If the confidence score is
   below ``CONFIDENCE_THRESHOLD`` (default 50), the email is treated as
   unparsed.

6. **Save** — a passing parse result is upserted into ``transactions``.
   Duplicates are detected via the ``txn_id`` field (bank-provided reference
   number) when present.  A previously unparsed message for the same Gmail
   message ID is removed from ``unparsed_messages``.

7. **Cursor** — after a successful Gmail history sync the new
   ``historyId`` is persisted to the ``ingest_cursor`` table so the next
   run fetches only new messages.

Adding a new bank / provider
-----------------------------
All classification and parsing logic lives in the database, so no Python
changes are required for most new banks.  Insert one row into each table:

``classifications``::

    sender_match_regex   = r"alerts@newbank\\.com"
    message_type         = "TRANSACTION_ALERT"
    priority             = 100          # higher wins
    is_active            = True

``parsers``::

    sender_match_regex   = r"alerts@newbank\\.com"
    body_match_regex     = r"debited|credited"   # optional pre-filter
    body_extract_regex   = (               # named groups → Transaction cols
        r"Acct (?P<account_id>\\w+) (?P<txn_isdebit>debited) "
        r"Rs\\.(?P<amount>[\\d,]+)"
    )
    provider             = "NewBank"
    priority             = 100
    is_active            = True

Supported named groups in ``body_extract_regex``:

=================  ==========================================
Group name         Effect
=================  ==========================================
``account_id``     Stored as-is (e.g. ``XX9999``)
``amount``         Parsed to ``float`` (commas stripped)
``txn_isdebit``    Any non-empty value → direction ``DEBIT``
``txn_iscredit``   Any non-empty value → direction ``CREDIT``
``txn_id``         Bank reference number (dedup key)
``merchant``       Merchant / payee name
``txn_datetime``   Parsed with ``dateutil.parser``
=================  ==========================================

If you need custom parsing logic (e.g. multi-step extraction or an API
call), subclass ``TransactionParser`` or add a pre-processing step in
``pipeline.py`` before the generic parser is invoked.
"""
