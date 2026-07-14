"""add user usage stats columns

Revision ID: d4b8c91f22ea
Revises: c3a9f1d7e824
Create Date: 2026-07-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8c91f22ea"
down_revision: str | Sequence[str] | None = "c3a9f1d7e824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("request_count")
        batch_op.drop_column("last_active_at")
        batch_op.drop_column("login_count")
        batch_op.drop_column("last_login_at")
