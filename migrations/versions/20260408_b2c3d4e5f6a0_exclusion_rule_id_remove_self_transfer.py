"""exclusion_rule_id traceability, parser-scoped exclusions, remove is_self_transfer

Revision ID: b2c3d4e5f6a0
Revises: a1b2c3d4e5f9
Create Date: 2026-04-08 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a0'
down_revision = 'a1b2c3d4e5f9'
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # --- transactions: add exclusion_rule_id, drop is_self_transfer ---
    t_cols = _cols("transactions")
    with op.batch_alter_table("transactions") as batch:
        if "exclusion_rule_id" not in t_cols:
            batch.add_column(sa.Column("exclusion_rule_id", sa.Integer(), nullable=True))
        if "is_self_transfer" in t_cols:
            batch.drop_column("is_self_transfer")

    # --- fetched_email_enrichments: add exclusion_rule_id ---
    e_cols = _cols("fetched_email_enrichments")
    with op.batch_alter_table("fetched_email_enrichments") as batch:
        if "exclusion_rule_id" not in e_cols:
            batch.add_column(sa.Column("exclusion_rule_id", sa.Integer(), nullable=True))

    # --- exclusion_rules: add parser_ids ---
    x_cols = _cols("exclusion_rules")
    with op.batch_alter_table("exclusion_rules") as batch:
        if "parser_ids" not in x_cols:
            batch.add_column(sa.Column("parser_ids", sa.String(), nullable=True))

    # --- parsers: drop is_self_transfer ---
    p_cols = _cols("parsers")
    if "is_self_transfer" in p_cols:
        with op.batch_alter_table("parsers") as batch:
            batch.drop_column("is_self_transfer")


def downgrade() -> None:
    # --- parsers: re-add is_self_transfer ---
    p_cols = _cols("parsers")
    if "is_self_transfer" not in p_cols:
        with op.batch_alter_table("parsers") as batch:
            batch.add_column(
                sa.Column("is_self_transfer", sa.Boolean(), server_default="0", nullable=False)
            )

    # --- exclusion_rules: drop parser_ids ---
    x_cols = _cols("exclusion_rules")
    if "parser_ids" in x_cols:
        with op.batch_alter_table("exclusion_rules") as batch:
            batch.drop_column("parser_ids")

    # --- fetched_email_enrichments: drop exclusion_rule_id ---
    e_cols = _cols("fetched_email_enrichments")
    if "exclusion_rule_id" in e_cols:
        with op.batch_alter_table("fetched_email_enrichments") as batch:
            batch.drop_column("exclusion_rule_id")

    # --- transactions: drop exclusion_rule_id, re-add is_self_transfer ---
    t_cols = _cols("transactions")
    with op.batch_alter_table("transactions") as batch:
        if "exclusion_rule_id" in t_cols:
            batch.drop_column("exclusion_rule_id")
        if "is_self_transfer" not in t_cols:
            batch.add_column(
                sa.Column("is_self_transfer", sa.Boolean(), server_default="0", nullable=False)
            )
