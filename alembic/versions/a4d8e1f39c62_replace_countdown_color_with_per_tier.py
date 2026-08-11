"""replace countdown color with per-tier colors

Premium countdown-pill colors on the Upcoming screen go from one scalar
override (users.upcoming_countdown_color, applied to the "urgent"/"soon"
tiers only) to a per-tier JSONB map (users.countdown_colors, keyed by
COUNTDOWN_TIERS: "urgent"/"soon"/"later"/"past"), same shape as the existing
status_colors column. Existing overrides are preserved by applying the old
single color to both tiers it used to cover.

Revision ID: a4d8e1f39c62
Revises: e2c8a4f1d936
Create Date: 2026-08-05 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a4d8e1f39c62"
down_revision: str | Sequence[str] | None = "e2c8a4f1d936"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("countdown_colors", postgresql.JSONB(), nullable=True))
    op.execute(
        """
        UPDATE users
        SET countdown_colors = jsonb_build_object('urgent', upcoming_countdown_color, 'soon', upcoming_countdown_color)
        WHERE upcoming_countdown_color IS NOT NULL
        """
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("upcoming_countdown_color")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("upcoming_countdown_color", sa.String(length=7), nullable=True))
    op.execute(
        "UPDATE users SET upcoming_countdown_color = countdown_colors ->> 'urgent' WHERE countdown_colors IS NOT NULL"
    )
    op.drop_column("users", "countdown_colors")
