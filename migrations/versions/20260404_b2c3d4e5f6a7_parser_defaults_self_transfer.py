"""Parser default account/category + self-transfer; transactions.is_self_transfer.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    p_cols = {c["name"] for c in insp.get_columns("parsers")}
    if "is_self_transfer" not in p_cols:
        with op.batch_alter_table("parsers") as batch:
            batch.add_column(
                sa.Column(
                    "is_self_transfer",
                    sa.Boolean(),
                    server_default=sa.text("0"),
                    nullable=False,
                )
            )
            batch.add_column(sa.Column("default_account_id", sa.String(), nullable=True))
            batch.add_column(sa.Column("default_category", sa.String(), nullable=True))

    t_cols = {c["name"] for c in insp.get_columns("transactions")}
    if "is_self_transfer" not in t_cols:
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(
                sa.Column(
                    "is_self_transfer",
                    sa.Boolean(),
                    server_default=sa.text("0"),
                    nullable=False,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    p_cols = {c["name"] for c in insp.get_columns("parsers")}
    if "is_self_transfer" in p_cols:
        with op.batch_alter_table("parsers") as batch:
            batch.drop_column("default_category")
            batch.drop_column("default_account_id")
            batch.drop_column("is_self_transfer")

    t_cols = {c["name"] for c in insp.get_columns("transactions")}
    if "is_self_transfer" in t_cols:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_column("is_self_transfer")
