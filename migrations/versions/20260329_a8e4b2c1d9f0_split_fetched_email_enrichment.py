"""Split fetched_emails raw vs enrichment tables.

Revision ID: a8e4b2c1d9f0
Revises: 5c1b7c4f7a3e
Create Date: 2026-03-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8e4b2c1d9f0"
down_revision: Union[str, None] = "5c1b7c4f7a3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fetched_email_enrichments",
        sa.Column(
            "fetched_emails_id",
            sa.String(),
            sa.ForeignKey("fetched_emails.gmail_message_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("classification_id", sa.Integer(), nullable=True),
        sa.Column("classification", sa.String(), nullable=True),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("parser_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("fetched_emails_id"),
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

    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("fetched_emails")}
    if "classification_id" in cols:
        bind.execute(
            sa.text(
                """
                INSERT INTO fetched_email_enrichments (
                    fetched_emails_id, classification_id, classification,
                    classification_reason, parser_id
                )
                SELECT gmail_message_id, classification_id, classification,
                       classification_reason, parser_id
                FROM fetched_emails
                """
            )
        )

    _drop_old_fetched_email_columns(bind)


def _drop_old_fetched_email_columns(bind) -> None:
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("fetched_emails")}
    idx_names = {ix["name"] for ix in insp.get_indexes("fetched_emails")}
    for name in (
        "ix_fetched_emails_parser_id",
        "ix_fetched_emails_classification_id",
    ):
        if name in idx_names:
            op.drop_index(name, table_name="fetched_emails")

    cols_to_drop = [
        "parser_id",
        "classification_id",
        "classification_reason",
        "classification",
    ]
    to_drop = [c for c in cols_to_drop if c in existing]
    if "updated_at" in existing:
        to_drop.append("updated_at")

    if not to_drop:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("fetched_emails") as batch:
            for col in to_drop:
                batch.drop_column(col)
    else:
        for col in to_drop:
            op.drop_column("fetched_emails", col)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("fetched_emails") as batch:
            batch.add_column(
                sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False)
            )
            batch.add_column(sa.Column("classification", sa.String(), nullable=True))
            batch.add_column(sa.Column("classification_reason", sa.Text(), nullable=True))
            batch.add_column(sa.Column("classification_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("parser_id", sa.Integer(), nullable=True))
    else:
        op.add_column(
            "fetched_emails",
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        )
        op.add_column("fetched_emails", sa.Column("classification", sa.String(), nullable=True))
        op.add_column("fetched_emails", sa.Column("classification_reason", sa.Text(), nullable=True))
        op.add_column("fetched_emails", sa.Column("classification_id", sa.Integer(), nullable=True))
        op.add_column("fetched_emails", sa.Column("parser_id", sa.Integer(), nullable=True))
        op.create_index(
            op.f("ix_fetched_emails_classification_id"),
            "fetched_emails",
            ["classification_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_fetched_emails_parser_id"),
            "fetched_emails",
            ["parser_id"],
            unique=False,
        )

    bind.execute(
        sa.text(
            """
            UPDATE fetched_emails
            SET classification_id = (
                SELECT classification_id FROM fetched_email_enrichments e
                WHERE e.fetched_emails_id = fetched_emails.gmail_message_id
            ),
            classification = (
                SELECT classification FROM fetched_email_enrichments e
                WHERE e.fetched_emails_id = fetched_emails.gmail_message_id
            ),
            classification_reason = (
                SELECT classification_reason FROM fetched_email_enrichments e
                WHERE e.fetched_emails_id = fetched_emails.gmail_message_id
            ),
            parser_id = (
                SELECT parser_id FROM fetched_email_enrichments e
                WHERE e.fetched_emails_id = fetched_emails.gmail_message_id
            )
            WHERE EXISTS (
                SELECT 1 FROM fetched_email_enrichments e
                WHERE e.fetched_emails_id = fetched_emails.gmail_message_id
            )
            """
        )
    )

    op.drop_index(op.f("ix_fetched_email_enrichments_parser_id"), table_name="fetched_email_enrichments")
    op.drop_index(
        op.f("ix_fetched_email_enrichments_classification_id"),
        table_name="fetched_email_enrichments",
    )
    op.drop_table("fetched_email_enrichments")
