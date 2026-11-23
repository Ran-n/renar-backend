#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/23 08:13:13.579073
Revised: 2026/11/23 08:13:13.579073
"""

"""restamp media_items.last_watched_at from watch history

Imports (TV Time and Renar export) wrote every watch with its real date but
never set media_items.last_watched_at, which Home's Watch Next list orders
by, so every imported show sorted as "never watched" in an arbitrary order.
This sets it to each in-progress or finished entry's latest real watch
(episode_watches or watch_events) wherever that is newer than what it has,
the same rule catalog/watch_next.py's restamp_last_watched applies after
every import from now on. Never moves a stamp backwards.

Downgrade is a no-op: the old values were missing or older than the history
says, and nothing reads them back.

Revision ID: f3a9c6e2b8d1
Revises: e8f2b5d1a7c4
Create Date: 2026-11-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c6e2b8d1"
down_revision: str | Sequence[str] | None = "e8f2b5d1a7c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        WITH latest AS (
            SELECT mi.id,
                   GREATEST(
                       (SELECT MAX(ew.watched_at) FROM episode_watches ew WHERE ew.media_item_id = mi.id),
                       (SELECT MAX(we.watched_at) FROM watch_events we WHERE we.media_item_id = mi.id)
                   ) AS watched_at
            FROM media_items mi
            WHERE mi.status IN ('watching', 'completed')
        )
        UPDATE media_items
        SET last_watched_at = latest.watched_at
        FROM latest
        WHERE media_items.id = latest.id
          AND latest.watched_at > COALESCE(media_items.last_watched_at, '1970-01-01'::timestamptz)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
