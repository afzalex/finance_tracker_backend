"""Add created_at / updated_at to fetched_email_enrichments.

Revision ID: c8d9e0f1a2b3
Revises: b5c6d7e8f9a0
Create Date: 2026-03-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("fetched_email_enrichments")}
    if "created_at" in cols:
        return

    # SQLite rejects ADD COLUMN ... DEFAULT CURRENT_TIMESTAMP (non-constant default).
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("fetched_email_enrichments") as batch:
            batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
            batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        bind.execute(
            sa.text(
                "UPDATE fetched_email_enrichments SET created_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            )
        )
        with op.batch_alter_table("fetched_email_enrichments") as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(),
                nullable=False,
            )
            batch.alter_column(
                "updated_at",
                existing_type=sa.DateTime(),
                nullable=False,
            )
    else:
        ts_default = sa.text("CURRENT_TIMESTAMP")
        op.add_column(
            "fetched_email_enrichments",
            sa.Column("created_at", sa.DateTime(), server_default=ts_default, nullable=False),
        )
        op.add_column(
            "fetched_email_enrichments",
            sa.Column("updated_at", sa.DateTime(), server_default=ts_default, nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("fetched_email_enrichments")}
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("fetched_email_enrichments") as batch:
            if "updated_at" in cols:
                batch.drop_column("updated_at")
            if "created_at" in cols:
                batch.drop_column("created_at")
    else:
        if "updated_at" in cols:
            op.drop_column("fetched_email_enrichments", "updated_at")
        if "created_at" in cols:
            op.drop_column("fetched_email_enrichments", "created_at")
