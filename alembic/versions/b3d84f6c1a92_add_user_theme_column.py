"""add user theme column

Revision ID: b3d84f6c1a92
Revises: e64c992f8b5e
Create Date: 2026-07-13 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d84f6c1a92"
down_revision: str | Sequence[str] | None = "e64c992f8b5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("theme", sa.String(length=20), nullable=False, server_default="gruvbox"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("theme")
