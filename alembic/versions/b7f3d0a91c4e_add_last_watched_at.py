#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/22 00:00:00.000000
Revised: 2026/07/22 00:00:00.000000
"""

"""add last_watched_at

media_items.last_watched_at: stamped only when the user marks an episode (or
a film) watched/rewatched, so Home's in-progress ordering can reflect genuine
watch activity instead of any row edit (favorite, rating, status, ...).

Revision ID: b7f3d0a91c4e
Revises: a4d6e1b8c2f7
Create Date: 2026-07-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f3d0a91c4e"
down_revision: str | Sequence[str] | None = "a4d6e1b8c2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("media_items", sa.Column("last_watched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_media_items_user_id_last_watched_at", "media_items", ["user_id", "last_watched_at"], unique=False
    )
    # Backfill from the closest thing to real history we have — each item's
    # own latest episode_watches row — so existing in-progress shows don't
    # all read as "never watched" and drop out of Home's activity order
    # until the user happens to watch something new. Items with no episode
    # rows (films, or shows tracked only via the coarse counters) fall back
    # to updated_at as a best-effort approximation.
    op.execute(
        """
        UPDATE media_items
        SET last_watched_at = COALESCE(
            (SELECT MAX(watched_at) FROM episode_watches WHERE episode_watches.media_item_id = media_items.id),
            media_items.updated_at
        )
        WHERE status = 'watching' OR status = 'completed'
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_media_items_user_id_last_watched_at", table_name="media_items")
    op.drop_column("media_items", "last_watched_at")
