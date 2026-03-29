"""Surrogate PK on fetched_emails; mail_id; FK int columns.

Revision ID: b5c6d7e8f9a0
Revises: a8e4b2c1d9f0
Create Date: 2026-03-29

- ``fetched_emails``: ``id`` INTEGER PK, ``mail_id`` UNIQUE (provider message id).
- ``fetched_email_enrichments.fetched_email_id`` → ``fetched_emails.id``.
- ``unparsed_messages.fetched_email_id`` → ``fetched_emails.id``.
- ``transactions.gmail_message_id`` renamed to ``mail_id``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a8e4b2c1d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    fe_cols = {c["name"] for c in insp.get_columns("fetched_emails")}
    if "gmail_message_id" in fe_cols:
        dialect = bind.dialect.name
        if dialect == "sqlite":
            _upgrade_sqlite(bind)
        elif dialect == "postgresql":
            _upgrade_postgresql(bind)
        else:
            raise NotImplementedError(
                f"Migration b5c6d7e8f9a0 does not support dialect {dialect!r}"
            )

    _rename_transactions_mail_column(bind)


def _upgrade_sqlite(bind) -> None:
    bind.execute(
        sa.text(
            """
            CREATE TABLE fetched_emails_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                mail_id VARCHAR NOT NULL,
                thread_id VARCHAR,
                subject VARCHAR,
                sender VARCHAR,
                snippet TEXT,
                internal_date_ms BIGINT NOT NULL,
                body_text TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (mail_id)
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO fetched_emails_new (
                mail_id, thread_id, subject, sender, snippet,
                internal_date_ms, body_text, created_at
            )
            SELECT
                gmail_message_id, thread_id, subject, sender, snippet,
                internal_date_ms, body_text, created_at
            FROM fetched_emails
            """
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE TABLE unparsed_messages_new (
                id INTEGER NOT NULL,
                fetched_email_id INTEGER NOT NULL,
                reason VARCHAR,
                classification_id INTEGER,
                parser_id INTEGER,
                created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                PRIMARY KEY (id),
                FOREIGN KEY (fetched_email_id) REFERENCES fetched_emails_new (id) ON DELETE CASCADE,
                FOREIGN KEY (classification_id) REFERENCES classifications (id) ON DELETE SET NULL,
                FOREIGN KEY (parser_id) REFERENCES parsers (id) ON DELETE SET NULL,
                UNIQUE (fetched_email_id)
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO unparsed_messages_new (
                id, fetched_email_id, reason, classification_id, parser_id, created_at
            )
            SELECT u.id, fe.id, u.reason, u.classification_id, u.parser_id, u.created_at
            FROM unparsed_messages u
            JOIN fetched_emails_new fe ON fe.mail_id = u.gmail_message_id
            """
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE TABLE fetched_email_enrichments_new (
                fetched_email_id INTEGER NOT NULL,
                classification_id INTEGER,
                classification VARCHAR,
                classification_reason TEXT,
                parser_id INTEGER,
                PRIMARY KEY (fetched_email_id),
                FOREIGN KEY (fetched_email_id) REFERENCES fetched_emails_new (id) ON DELETE CASCADE
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO fetched_email_enrichments_new (
                fetched_email_id, classification_id, classification,
                classification_reason, parser_id
            )
            SELECT fe.id, e.classification_id, e.classification,
                   e.classification_reason, e.parser_id
            FROM fetched_email_enrichments e
            JOIN fetched_emails_new fe ON fe.mail_id = e.fetched_emails_id
            """
        )
    )

    bind.execute(sa.text("DROP TABLE unparsed_messages"))
    bind.execute(sa.text("DROP TABLE fetched_email_enrichments"))
    bind.execute(sa.text("DROP TABLE fetched_emails"))
    bind.execute(sa.text("ALTER TABLE fetched_emails_new RENAME TO fetched_emails"))
    bind.execute(sa.text("ALTER TABLE unparsed_messages_new RENAME TO unparsed_messages"))
    bind.execute(
        sa.text("ALTER TABLE fetched_email_enrichments_new RENAME TO fetched_email_enrichments")
    )

    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_fetched_emails_internal_date_ms "
            "ON fetched_emails (internal_date_ms)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_fetched_email_enrichments_classification_id "
            "ON fetched_email_enrichments (classification_id)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_fetched_email_enrichments_parser_id "
            "ON fetched_email_enrichments (parser_id)"
        )
    )


def _upgrade_postgresql(bind) -> None:
    bind.execute(
        sa.text(
            """
            CREATE TABLE fetched_emails_new (
                id SERIAL PRIMARY KEY,
                mail_id VARCHAR NOT NULL UNIQUE,
                thread_id VARCHAR,
                subject VARCHAR,
                sender VARCHAR,
                snippet TEXT,
                internal_date_ms BIGINT NOT NULL,
                body_text TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO fetched_emails_new (
                mail_id, thread_id, subject, sender, snippet,
                internal_date_ms, body_text, created_at
            )
            SELECT
                gmail_message_id, thread_id, subject, sender, snippet,
                internal_date_ms, body_text, created_at
            FROM fetched_emails
            """
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE TABLE unparsed_messages_new (
                id INTEGER NOT NULL,
                fetched_email_id INTEGER NOT NULL REFERENCES fetched_emails_new (id) ON DELETE CASCADE,
                reason VARCHAR,
                classification_id INTEGER REFERENCES classifications (id) ON DELETE SET NULL,
                parser_id INTEGER REFERENCES parsers (id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE (fetched_email_id)
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO unparsed_messages_new (
                id, fetched_email_id, reason, classification_id, parser_id, created_at
            )
            SELECT u.id, fe.id, u.reason, u.classification_id, u.parser_id, u.created_at
            FROM unparsed_messages u
            JOIN fetched_emails_new fe ON fe.mail_id = u.gmail_message_id
            """
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE TABLE fetched_email_enrichments_new (
                fetched_email_id INTEGER NOT NULL PRIMARY KEY
                    REFERENCES fetched_emails_new (id) ON DELETE CASCADE,
                classification_id INTEGER,
                classification VARCHAR,
                classification_reason TEXT,
                parser_id INTEGER
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO fetched_email_enrichments_new (
                fetched_email_id, classification_id, classification,
                classification_reason, parser_id
            )
            SELECT fe.id, e.classification_id, e.classification,
                   e.classification_reason, e.parser_id
            FROM fetched_email_enrichments e
            JOIN fetched_emails_new fe ON fe.mail_id = e.fetched_emails_id
            """
        )
    )

    bind.execute(sa.text("DROP TABLE unparsed_messages"))
    bind.execute(sa.text("DROP TABLE fetched_email_enrichments"))
    bind.execute(sa.text("DROP TABLE fetched_emails"))
    bind.execute(sa.text("ALTER TABLE fetched_emails_new RENAME TO fetched_emails"))
    bind.execute(sa.text("ALTER TABLE unparsed_messages_new RENAME TO unparsed_messages"))
    bind.execute(
        sa.text("ALTER TABLE fetched_email_enrichments_new RENAME TO fetched_email_enrichments")
    )

    op.create_index(
        op.f("ix_fetched_emails_internal_date_ms"),
        "fetched_emails",
        ["internal_date_ms"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fetched_email_enrichments_classification_id"),
        "fetched_email_enrichments",
        ["classification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fetched_email_enrichments_parser_id"),
        "fetched_email_enrichments",
        ["parser_id"],
        unique=False,
    )


def _rename_transactions_mail_column(bind) -> None:
    insp = sa.inspect(bind)
    txn_cols = {c["name"] for c in insp.get_columns("transactions")}
    if "gmail_message_id" not in txn_cols:
        return
    idx_names = {ix["name"] for ix in insp.get_indexes("transactions")}
    old_ix = op.f("ix_transactions_gmail_message_id")
    new_ix = op.f("ix_transactions_mail_id")
    if old_ix in idx_names:
        op.drop_index(old_ix, table_name="transactions")
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("gmail_message_id", new_column_name="mail_id")
    op.create_index(new_ix, "transactions", ["mail_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade from surrogate-key fetched_emails is not supported; restore from backup."
    )
