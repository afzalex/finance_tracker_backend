"""Add parser_id/classification_id enrichment to fetched_emails.

Revision ID: 5c1b7c4f7a3e
Revises: 473df53e6294
Create Date: 2026-03-24

SQLite cannot add foreign keys via ALTER; we store integer FKs without DB-level
constraints (matches the ORM, which uses plain Integer columns).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5c1b7c4f7a3e"
down_revision: Union[str, None] = "473df53e6294"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("fetched_emails")}
    index_names = {ix["name"] for ix in insp.get_indexes("fetched_emails")}

    if "classification_id" not in col_names:
        op.add_column(
            "fetched_emails",
            sa.Column("classification_id", sa.Integer(), nullable=True),
        )
    if "parser_id" not in col_names:
        op.add_column(
            "fetched_emails",
            sa.Column("parser_id", sa.Integer(), nullable=True),
        )

    cls_ix = op.f("ix_fetched_emails_classification_id")
    par_ix = op.f("ix_fetched_emails_parser_id")
    if cls_ix not in index_names:
        op.create_index(cls_ix, "fetched_emails", ["classification_id"], unique=False)
    if par_ix not in index_names:
        op.create_index(par_ix, "fetched_emails", ["parser_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("fetched_emails")}
    index_names = {ix["name"] for ix in insp.get_indexes("fetched_emails")}

    cls_ix = op.f("ix_fetched_emails_classification_id")
    par_ix = op.f("ix_fetched_emails_parser_id")
    if cls_ix in index_names:
        op.drop_index(cls_ix, table_name="fetched_emails")
    if par_ix in index_names:
        op.drop_index(par_ix, table_name="fetched_emails")

    if "parser_id" in col_names:
        op.drop_column("fetched_emails", "parser_id")
    if "classification_id" in col_names:
        op.drop_column("fetched_emails", "classification_id")
