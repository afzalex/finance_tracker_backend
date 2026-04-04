"""Add id and mail_account_id to app_config; 0 = system scope.

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-04-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError(
            "Revision a1b2c3d4e5f6 only supports SQLite (table rebuild). "
            "Port the RENAME + copy steps for your database or run manually."
        )
    insp = sa.inspect(bind)
    if "app_config" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("app_config")}
    if "mail_account_id" in cols:
        return

    op.execute(sa.text("ALTER TABLE app_config RENAME TO app_config_old"))
    op.create_table(
        "app_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mail_account_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mail_account_id", "key", name="uq_app_config_mail_account_key"),
    )
    op.create_index(
        op.f("ix_app_config_mail_account_id"),
        "app_config",
        ["mail_account_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO app_config (mail_account_id, key, value, updated_at) "
            "SELECT 0, key, value, updated_at FROM app_config_old"
        )
    )
    op.drop_table("app_config_old")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Revision a1b2c3d4e5f6 downgrade is SQLite-only.")
    insp = sa.inspect(bind)
    if "app_config" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("app_config")}
    if "mail_account_id" not in cols:
        return

    op.execute(sa.text("ALTER TABLE app_config RENAME TO app_config_new"))
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    # Keep only system rows; if duplicate keys existed across accounts, last wins in SQLite.
    op.execute(
        sa.text(
            "INSERT OR REPLACE INTO app_config (key, value, updated_at) "
            "SELECT key, value, updated_at FROM app_config_new WHERE mail_account_id = 0"
        )
    )
    op.drop_table("app_config_new")
