"""add_exclusion_rules

Revision ID: a1b2c3d4e5f9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-08 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('exclusion_rules',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('sender_match_regex', sa.String(), nullable=True),
        sa.Column('subject_match_regex', sa.String(), nullable=True),
        sa.Column('body_match_regex', sa.String(), nullable=True),
        sa.Column('snippet_match_regex', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.add_column('transactions', sa.Column('is_excluded', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    # Note: SQLite has limited support for dropping columns.
    # In a real environment with batch mode, you would use batch_alter_table.
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('is_excluded')
    op.drop_table('exclusion_rules')
