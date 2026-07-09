"""add login_events table

Revision ID: f7a3c0e91b45
Revises: d4b8c91f22ea
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a3c0e91b45'
down_revision: Union[str, Sequence[str], None] = 'd4b8c91f22ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('login_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_events_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('login_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_login_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_login_events_user_id'))

    op.drop_table('login_events')
