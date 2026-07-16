"""add user has_seen_welcome

Revision ID: a3d8e2c1b4f7
Revises: 90ff1af0f0ad
Create Date: 2026-07-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d8e2c1b4f7"
down_revision: str | Sequence[str] | None = "90ff1af0f0ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("has_seen_welcome", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("has_seen_welcome")
