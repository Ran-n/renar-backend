"""add strikes table and user ban columns

Revision ID: 2b07a12077a1
Revises: f20e0cd1ab74
Create Date: 2026-07-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b07a12077a1"
down_revision: str | Sequence[str] | None = "f20e0cd1ab74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "strikes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_offense_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("strikes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_strikes_ip"), ["ip"], unique=True)

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("banned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("ban_reason", sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f("ix_users_banned"), ["banned"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_banned"))
        batch_op.drop_column("ban_reason")
        batch_op.drop_column("banned")

    with op.batch_alter_table("strikes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_strikes_ip"))

    op.drop_table("strikes")
