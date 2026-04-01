"""Add processing_time_ms to fetched_email_enrichments.

Revision ID: d1e2f3a4b5c6
Revises: c8d9e0f1a2b3
Create Date: 2026-04-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("fetched_email_enrichments")}
    if "processing_time_ms" in cols:
        return
    with op.batch_alter_table("fetched_email_enrichments") as batch:
        batch.add_column(sa.Column("processing_time_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("fetched_email_enrichments")}
    if "processing_time_ms" not in cols:
        return
    with op.batch_alter_table("fetched_email_enrichments") as batch:
        batch.drop_column("processing_time_ms")
