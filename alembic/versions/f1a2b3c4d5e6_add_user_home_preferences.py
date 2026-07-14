"""add user home preferences

Revision ID: f1a2b3c4d5e6
Revises: c8a1d5e6f709
Create Date: 2026-07-14 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "c8a1d5e6f709"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("home_hero_enabled", sa.Boolean(), nullable=False, server_default="true"))
        batch_op.add_column(sa.Column("home_on_launch", sa.Boolean(), nullable=False, server_default="true"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("home_on_launch")
        batch_op.drop_column("home_hero_enabled")
