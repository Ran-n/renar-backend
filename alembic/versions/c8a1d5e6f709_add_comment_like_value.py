"""add comment like value

Revision ID: c8a1d5e6f709
Revises: b3d84f6c1a92
Create Date: 2026-07-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8a1d5e6f709"
down_revision: str | Sequence[str] | None = "b3d84f6c1a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("comment_likes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("value", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("comment_likes", schema=None) as batch_op:
        batch_op.drop_column("value")
