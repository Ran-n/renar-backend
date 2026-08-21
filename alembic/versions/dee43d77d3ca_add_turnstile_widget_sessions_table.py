"""add turnstile widget sessions table

Revision ID: dee43d77d3ca
Revises: 5382045571f2
Create Date: 2026-08-20 20:17:19.408108

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dee43d77d3ca"
down_revision: str | Sequence[str] | None = "5382045571f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "turnstile_widget_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("turnstile_widget_sessions")
