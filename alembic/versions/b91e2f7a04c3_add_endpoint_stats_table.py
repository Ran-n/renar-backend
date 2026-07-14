"""add endpoint_stats table

Revision ID: b91e2f7a04c3
Revises: f7a3c0e91b45
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b91e2f7a04c3"
down_revision: str | Sequence[str] | None = "f7a3c0e91b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "endpoint_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("method", "path", "user_id", name="uq_endpoint_stat"),
    )
    with op.batch_alter_table("endpoint_stats", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_endpoint_stats_path"), ["path"], unique=False)
        batch_op.create_index(batch_op.f("ix_endpoint_stats_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("endpoint_stats", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_endpoint_stats_user_id"))
        batch_op.drop_index(batch_op.f("ix_endpoint_stats_path"))

    op.drop_table("endpoint_stats")
