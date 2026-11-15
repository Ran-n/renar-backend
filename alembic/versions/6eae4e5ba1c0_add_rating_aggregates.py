#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/17 00:00:00.000000
Revised: 2026/11/15 11:01:43.816430
"""

"""add rating aggregates

Adds titles.rating_sum/rating_count and the episode_rating_aggregates
table, both maintained incrementally by database triggers (see
db_triggers.py's RATING_AGGREGATES_TRIGGER_SQL) — same pattern as
total_watch_minutes/total_users. /media/ratings, /media/ratings/batch and
/media/episode-ratings previously recomputed their average by live-
aggregating every matching media_items/episode_watches row on every single
call (title_ratings even pulled every individual rating value over the wire
into Python just to sum() them there) — fine at today's scale, but that cost
scales with how many people rated the exact title/episode being read, which
is precisely the number that grows fastest for a popular title, and it was
paid again on every read. This makes a read an O(1) point lookup instead.

Backfilled from existing data below so this stays correct for
already-rated titles/episodes, not just ones rated after this migration.

Revision ID: 6eae4e5ba1c0
Revises: a4d8e1f39c62
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6eae4e5ba1c0"
down_revision: str | Sequence[str] | None = "a4d8e1f39c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the trigger SQL as it stood when this migration was written.
# Never import it from renar_backend.db_triggers: that module holds today's
# SQL, which may name columns a later migration adds, so replaying the
# history on an empty database would fail here (it did; see
# tests/test_migrations.py).
_RATING_AGGREGATES_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION trg_media_items_rating() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.rating IS NOT NULL THEN
            UPDATE titles SET rating_sum = rating_sum - OLD.rating, rating_count = rating_count - 1
            WHERE id = OLD.title_id;
        END IF;
        RETURN OLD;
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.rating IS NOT NULL THEN
            UPDATE titles SET rating_sum = rating_sum + NEW.rating, rating_count = rating_count + 1
            WHERE id = NEW.title_id;
        END IF;
        RETURN NEW;
    ELSE -- UPDATE, rating changed (guarded by the trigger's own WHEN clause)
        UPDATE titles
        SET rating_sum = rating_sum + COALESCE(NEW.rating, 0) - COALESCE(OLD.rating, 0),
            rating_count = rating_count
                + (CASE WHEN NEW.rating IS NOT NULL THEN 1 ELSE 0 END)
                - (CASE WHEN OLD.rating IS NOT NULL THEN 1 ELSE 0 END)
        WHERE id = NEW.title_id;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS media_items_rating_iud ON media_items;
CREATE TRIGGER media_items_rating_iud
AFTER INSERT OR DELETE ON media_items
FOR EACH ROW EXECUTE FUNCTION trg_media_items_rating();

DROP TRIGGER IF EXISTS media_items_rating_update ON media_items;
CREATE TRIGGER media_items_rating_update
AFTER UPDATE ON media_items
FOR EACH ROW
WHEN (OLD.rating IS DISTINCT FROM NEW.rating)
EXECUTE FUNCTION trg_media_items_rating();

CREATE OR REPLACE FUNCTION trg_episode_watches_rating() RETURNS trigger AS $$
DECLARE
    v_title_id integer;
    v_season integer;
    v_episode integer;
    delta_sum integer;
    delta_count integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.rating IS NULL THEN
            RETURN OLD;
        END IF;
        SELECT title_id INTO v_title_id FROM media_items WHERE id = OLD.media_item_id;
        v_season := OLD.season;
        v_episode := OLD.episode;
        delta_sum := -OLD.rating;
        delta_count := -1;
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.rating IS NULL THEN
            RETURN NEW;
        END IF;
        SELECT title_id INTO v_title_id FROM media_items WHERE id = NEW.media_item_id;
        v_season := NEW.season;
        v_episode := NEW.episode;
        delta_sum := NEW.rating;
        delta_count := 1;
    ELSE -- UPDATE, rating changed (guarded by the trigger's own WHEN clause)
        SELECT title_id INTO v_title_id FROM media_items WHERE id = NEW.media_item_id;
        v_season := NEW.season;
        v_episode := NEW.episode;
        delta_sum := COALESCE(NEW.rating, 0) - COALESCE(OLD.rating, 0);
        delta_count := (CASE WHEN NEW.rating IS NOT NULL THEN 1 ELSE 0 END)
                      - (CASE WHEN OLD.rating IS NOT NULL THEN 1 ELSE 0 END);
    END IF;

    INSERT INTO episode_rating_aggregates (title_id, season, episode, rating_sum, rating_count)
    VALUES (v_title_id, v_season, v_episode, delta_sum, delta_count)
    ON CONFLICT (title_id, season, episode) DO UPDATE
    SET rating_sum = episode_rating_aggregates.rating_sum + EXCLUDED.rating_sum,
        rating_count = episode_rating_aggregates.rating_count + EXCLUDED.rating_count;

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS episode_watches_rating_iud ON episode_watches;
CREATE TRIGGER episode_watches_rating_iud
AFTER INSERT OR DELETE ON episode_watches
FOR EACH ROW EXECUTE FUNCTION trg_episode_watches_rating();

DROP TRIGGER IF EXISTS episode_watches_rating_update ON episode_watches;
CREATE TRIGGER episode_watches_rating_update
AFTER UPDATE ON episode_watches
FOR EACH ROW
WHEN (OLD.rating IS DISTINCT FROM NEW.rating)
EXECUTE FUNCTION trg_episode_watches_rating();
"""

_RATING_AGGREGATES_TRIGGER_TEARDOWN_SQL = """
DROP TRIGGER IF EXISTS episode_watches_rating_update ON episode_watches;
DROP TRIGGER IF EXISTS episode_watches_rating_iud ON episode_watches;
DROP FUNCTION IF EXISTS trg_episode_watches_rating();
DROP TRIGGER IF EXISTS media_items_rating_update ON media_items;
DROP TRIGGER IF EXISTS media_items_rating_iud ON media_items;
DROP FUNCTION IF EXISTS trg_media_items_rating();
"""


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rating_sum", sa.BigInteger(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "episode_rating_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id"), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("rating_sum", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("title_id", "season", "episode", name="uq_episode_rating_aggregate"),
    )
    op.create_index("ix_episode_rating_aggregates_title_id", "episode_rating_aggregates", ["title_id"])

    # Backfill from existing ratings, so titles/episodes rated before this
    # migration start with a correct total rather than 0 — the triggers
    # created below only cover writes from this point on.
    op.execute(
        """
        UPDATE titles
        SET rating_sum = sub.s, rating_count = sub.c
        FROM (
            SELECT title_id, SUM(rating) AS s, COUNT(rating) AS c
            FROM media_items
            WHERE rating IS NOT NULL
            GROUP BY title_id
        ) AS sub
        WHERE titles.id = sub.title_id
        """
    )
    op.execute(
        """
        INSERT INTO episode_rating_aggregates (title_id, season, episode, rating_sum, rating_count)
        SELECT mi.title_id, ew.season, ew.episode, SUM(ew.rating), COUNT(ew.rating)
        FROM episode_watches ew
        JOIN media_items mi ON mi.id = ew.media_item_id
        WHERE ew.rating IS NOT NULL
        GROUP BY mi.title_id, ew.season, ew.episode
        """
    )

    op.execute(_RATING_AGGREGATES_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(_RATING_AGGREGATES_TRIGGER_TEARDOWN_SQL)

    op.drop_index("ix_episode_rating_aggregates_title_id", table_name="episode_rating_aggregates")
    op.drop_table("episode_rating_aggregates")

    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.drop_column("rating_count")
        batch_op.drop_column("rating_sum")
