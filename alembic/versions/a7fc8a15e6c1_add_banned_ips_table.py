"""add banned_ips table

Revision ID: a7fc8a15e6c1
Revises: bd1df53928c4
Create Date: 2026-07-07 18:43:21.420077

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7fc8a15e6c1'
down_revision: Union[str, Sequence[str], None] = 'bd1df53928c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'banned_ips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('banned_ips', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_banned_ips_ip'), ['ip'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('banned_ips', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_banned_ips_ip'))

    op.drop_table('banned_ips')
