"""add request_days table

Revision ID: c2d5e83f1a67
Revises: b91e2f7a04c3
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d5e83f1a67'
down_revision: Union[str, Sequence[str], None] = 'b91e2f7a04c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'request_days',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'day', name='uq_request_day'),
    )
    with op.batch_alter_table('request_days', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_request_days_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_request_days_day'), ['day'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('request_days', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_request_days_day'))
        batch_op.drop_index(batch_op.f('ix_request_days_user_id'))

    op.drop_table('request_days')
