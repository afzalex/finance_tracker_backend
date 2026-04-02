"""Replace ingest_cursor with generic app_config key/value table.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KEY_INTERNAL_GMAIL_HISTORY_ID = "internal.mail.gmail.history_id"
KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT = "internal.mail.ingest.last_run_at"

KEY_APP_GMAIL_LABELS = "app.mail.gmail.labels"
KEY_APP_POLL_SECONDS = "app.mail.poll_seconds"
KEY_APP_INITIAL_LOOKBACK_DAYS = "app.mail.initial_lookback_days"
KEY_APP_CONFIDENCE_THRESHOLD = "app.ingest.confidence_threshold"


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "app_config" in tables:
        # Table exists already (e.g. created earlier in dev) — still ensure required defaults exist.
        bind.execute(
            sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
            {"k": KEY_APP_GMAIL_LABELS, "v": "Finance"},
        )
        bind.execute(
            sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
            {"k": KEY_APP_POLL_SECONDS, "v": "300"},
        )
        bind.execute(
            sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
            {"k": KEY_APP_INITIAL_LOOKBACK_DAYS, "v": "30"},
        )
        bind.execute(
            sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
            {"k": KEY_APP_CONFIDENCE_THRESHOLD, "v": "50"},
        )
        if "ingest_cursor" in tables:
            op.drop_table("ingest_cursor")
        return

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    # Seed default runtime config into DB (no hardcoded defaults in Python code).
    bind.execute(
        sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
        {"k": KEY_APP_GMAIL_LABELS, "v": "Finance"},
    )
    bind.execute(
        sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
        {"k": KEY_APP_POLL_SECONDS, "v": "300"},
    )
    bind.execute(
        sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
        {"k": KEY_APP_INITIAL_LOOKBACK_DAYS, "v": "30"},
    )
    bind.execute(
        sa.text("INSERT OR IGNORE INTO app_config (key, value) VALUES (:k, :v)"),
        {"k": KEY_APP_CONFIDENCE_THRESHOLD, "v": "50"},
    )

    if "ingest_cursor" in tables:
        row = bind.execute(
            sa.text(
                "SELECT gmail_history_id, last_run_at FROM ingest_cursor ORDER BY id LIMIT 1"
            )
        ).fetchone()
        if row is not None:
            hid, lra = row[0], row[1]
            if hid:
                bind.execute(
                    sa.text(
                        "INSERT INTO app_config (key, value) VALUES (:k, :v)"
                    ),
                    {"k": KEY_INTERNAL_GMAIL_HISTORY_ID, "v": hid},
                )
            if lra is not None:
                if hasattr(lra, "isoformat"):
                    v = lra.isoformat()
                else:
                    v = str(lra)
                bind.execute(
                    sa.text(
                        "INSERT INTO app_config (key, value) VALUES (:k, :v)"
                    ),
                    {"k": KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT, "v": v},
                )
        op.drop_table("ingest_cursor")


def downgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "app_config" not in tables:
        return
    if "ingest_cursor" in tables:
        return

    op.create_table(
        "ingest_cursor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gmail_history_id", sa.String(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    if "app_config" in sa.inspect(bind).get_table_names():
        hid = bind.execute(
            sa.text("SELECT value FROM app_config WHERE key = :k"),
            {"k": KEY_INTERNAL_GMAIL_HISTORY_ID},
        ).scalar()
        lra_raw = bind.execute(
            sa.text("SELECT value FROM app_config WHERE key = :k"),
            {"k": KEY_INTERNAL_MAIL_INGEST_LAST_RUN_AT},
        ).scalar()
        if hid or lra_raw:
            from datetime import datetime

            last_run = None
            if lra_raw:
                try:
                    last_run = datetime.fromisoformat(lra_raw.replace("Z", "+00:00"))
                except ValueError:
                    last_run = None
            bind.execute(
                sa.text(
                    "INSERT INTO ingest_cursor (gmail_history_id, last_run_at) VALUES (:h, :t)"
                ),
                {"h": hid, "t": last_run},
            )
        op.drop_table("app_config")
