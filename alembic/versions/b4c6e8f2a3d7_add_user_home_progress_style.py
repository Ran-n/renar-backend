"""add user home progress style

Revision ID: b4c6e8f2a3d7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-14 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c6e8f2a3d7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("home_progress_style", sa.String(length=20), nullable=False, server_default="rings")
        )
        batch_op.add_column(sa.Column("home_season_color", sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column("home_series_color", sa.String(length=7), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("home_series_color")
        batch_op.drop_column("home_season_color")
        batch_op.drop_column("home_progress_style")
