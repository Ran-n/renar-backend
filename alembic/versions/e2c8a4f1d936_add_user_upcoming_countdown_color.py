"""add user upcoming countdown color

Revision ID: e2c8a4f1d936
Revises: b5f3a1c9d7e2
Create Date: 2026-08-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c8a4f1d936"
down_revision: str | Sequence[str] | None = "b5f3a1c9d7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("upcoming_countdown_color", sa.String(length=7), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("upcoming_countdown_color")
