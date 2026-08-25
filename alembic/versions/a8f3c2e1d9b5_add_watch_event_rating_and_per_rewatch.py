#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/21 21:44:14.595351
Revised: 2026/08/21 21:44:14.595351
"""

"""add per-rewatch ratings (watch_events.rating + is_initial)

Revision ID: a8f3c2e1d9b5
Revises: f6d5c84349df
Create Date: 2026-08-21 00:00:00.000000

Adds two columns to watch_events:
  - rating (Integer, nullable): per-watch-through rating on the 1-100 scale,
    the source of truth for per-rewatch rating history. LibraryEntry.rating
    and EpisodeWatch.rating remain as the denormalized "latest rating" cache
    that the existing database triggers (trg_media_items_rating,
    trg_episode_watches_rating) read unchanged — application code keeps them
    in sync via _write_rating() in routers/media.py.
  - is_initial (Boolean, nullable): True for the first-watch event created
    by set_episode / create_media / update_media; NULL for rewatch events
    (including all pre-migration rows — treated as rewatches for backward
    compat). Used to exclude initial-watch events from the rewatch_count
    display so adding a first-watch WatchEvent doesn't inflate the count.

Backfill creates one initial-watch WatchEvent (is_initial=TRUE) for every
rated item/episode that has no existing WatchEvent yet, preserving existing
ratings as history for the first watch. Items with existing WatchEvents
(already rewatched before this migration) are left as-is: their most recent
WatchEvent was a genuine rewatch and gets rating=NULL; the history for
earlier watches is unavailable (it was never recorded) and cannot be
reconstructed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3c2e1d9b5"
down_revision: str | Sequence[str] | None = "f6d5c84349df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("watch_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rating", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_initial", sa.Boolean(), nullable=True))

    # Backfill: for each rated film (media_items row with rating IS NOT NULL)
    # that has no existing film-scope WatchEvent (season IS NULL AND episode IS
    # NULL), insert one initial-watch event so the rating isn't orphaned from
    # history. watched_at falls back to updated_at when last_watched_at is NULL
    # (e.g. an item that was rated but never explicitly marked as watched).
    op.execute(
        """
        INSERT INTO watch_events (media_item_id, season, episode, watched_at, rating, is_initial)
        SELECT
            mi.id,
            NULL,
            NULL,
            COALESCE(mi.last_watched_at, mi.updated_at),
            mi.rating,
            TRUE
        FROM media_items mi
        WHERE mi.rating IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM watch_events we
              WHERE we.media_item_id = mi.id
                AND we.season IS NULL
                AND we.episode IS NULL
          )
        """
    )

    # Backfill: same for rated episodes (episode_watches row with rating IS
    # NOT NULL) that have no existing WatchEvent for that (media_item_id,
    # season, episode) scope. Uses the EpisodeWatch's own watched_at as the
    # timestamp (the closest proxy for when the episode was first watched).
    op.execute(
        """
        INSERT INTO watch_events (media_item_id, season, episode, watched_at, rating, is_initial)
        SELECT
            ew.media_item_id,
            ew.season,
            ew.episode,
            ew.watched_at,
            ew.rating,
            TRUE
        FROM episode_watches ew
        WHERE ew.rating IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM watch_events we
              WHERE we.media_item_id = ew.media_item_id
                AND we.season = ew.season
                AND we.episode = ew.episode
          )
        """
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the two new columns only. The backfilled WatchEvent rows stay in
    place: they are genuine event records (one row = one watch), not derived
    data, and removing them would silently discard rating history that any
    post-upgrade write may have created. Callers downgrading should accept
    that the extra rows are effectively inert without the rating column.
    """
    with op.batch_alter_table("watch_events", schema=None) as batch_op:
        batch_op.drop_column("is_initial")
        batch_op.drop_column("rating")
