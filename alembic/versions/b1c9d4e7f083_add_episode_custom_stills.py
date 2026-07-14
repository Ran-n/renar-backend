"""add episode custom stills

Premium per-episode still override, same shape as the existing
custom-poster/custom-backdrop overrides but on its own table (keyed on
media_item_id/season/episode) since EpisodeWatch's row existence already
means "watched" and must not be conflated with "has a custom still".

Revision ID: b1c9d4e7f083
Revises: 94328cc855c2
Create Date: 2026-07-14 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c9d4e7f083"
down_revision: str | Sequence[str] | None = "94328cc855c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "episode_custom_stills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("still_image_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"]),
        sa.ForeignKeyConstraint(["still_image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_item_id", "season", "episode", name="uq_item_episode_custom_still"),
    )
    op.create_index(
        op.f("ix_episode_custom_stills_media_item_id"), "episode_custom_stills", ["media_item_id"], unique=False
    )
    op.create_index(
        op.f("ix_episode_custom_stills_still_image_id"), "episode_custom_stills", ["still_image_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_episode_custom_stills_still_image_id"), table_name="episode_custom_stills")
    op.drop_index(op.f("ix_episode_custom_stills_media_item_id"), table_name="episode_custom_stills")
    op.drop_table("episode_custom_stills")
