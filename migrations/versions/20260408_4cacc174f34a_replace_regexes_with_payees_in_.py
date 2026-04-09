"""replace regexes with payees in exclusion_rules

Revision ID: 4cacc174f34a
Revises: b2c3d4e5f6a0
Create Date: 2026-04-08 16:27:28.305702+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cacc174f34a'
down_revision: Union[str, None] = 'b2c3d4e5f6a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('exclusion_rules') as batch_op:
        batch_op.add_column(sa.Column('payees', sa.String(), nullable=True))
        batch_op.drop_column('sender_match_regex')
        batch_op.drop_column('snippet_match_regex')
        batch_op.drop_column('subject_match_regex')
        batch_op.drop_column('body_match_regex')


def downgrade() -> None:
    with op.batch_alter_table('exclusion_rules') as batch_op:
        batch_op.add_column(sa.Column('body_match_regex', sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column('subject_match_regex', sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column('snippet_match_regex', sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column('sender_match_regex', sa.VARCHAR(), nullable=True))
        batch_op.drop_column('payees')

