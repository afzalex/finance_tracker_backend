"""Add mail_accounts for DB-backed OAuth tokens.

Revision ID: f7a8b9c0d1e2
Revises: e2f3a4b5c6d7
Create Date: 2026-04-04
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mail_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("account_mail_id", sa.String(length=320), nullable=True),
        sa.Column("token_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "account_mail_id", name="uq_mail_accounts_provider_email"),
    )
    op.create_index(op.f("ix_mail_accounts_provider"), "mail_accounts", ["provider"], unique=False)

    # Optional: import legacy secrets/token.json into first primary Gmail row.
    try:
        from backend.config import settings
    except Exception:
        return
    rel = settings.gmail_token_file
    candidates = [
        Path(rel),
        Path(__file__).resolve().parents[2] / rel,
    ]
    for token_path in candidates:
        if not token_path.is_file():
            continue
        try:
            raw = token_path.read_text(encoding="utf-8")
        except OSError:
            break
        if not raw.strip():
            break
        bind = op.get_bind()
        bind.execute(
            sa.text(
                "INSERT INTO mail_accounts (provider, account_mail_id, token_json, is_active, is_primary) "
                "VALUES ('gmail', NULL, :tj, 1, 1)"
            ),
            {"tj": raw},
        )
        break


def downgrade() -> None:
    op.drop_index(op.f("ix_mail_accounts_provider"), table_name="mail_accounts")
    op.drop_table("mail_accounts")
