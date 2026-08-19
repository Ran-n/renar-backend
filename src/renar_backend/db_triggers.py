#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/16 09:54:55.646441
Revised: 2026/08/18 17:25:24.090648

Postgres functions/triggers that keep denormalized aggregate columns in sync
at the database level — see docs/design-decisions.md, "users.total_watch_minutes:
a stored aggregate, maintained by a database trigger, not application code",
and its app_counters.total_users counterpart.

Defined once here, not inlined in the Alembic migration, because it's used in
two places that must never drift apart:

- alembic/versions/a7c2e9f4b816_*.py, which creates it for real deployments.
- models.py, registering it against each relevant table's own "after_create"
  event — what makes it exist in the schema tests build via
  Base.metadata.create_all(), since tests don't run Alembic migrations
  (see tests/conftest.py).

The triggers maintain their columns incrementally (O(1) per row change),
not by re-aggregating on every write. OLD/NEW give the trigger exactly the
before/after values it needs to compute a delta, so this doesn't carry the
same risk as an app-level delta would: the two states are guaranteed
consistent by Postgres itself, in one place, not hand-computed at scattered
call sites.
"""

from .constants import DEFAULT_EPISODE_RUNTIME as _DEFAULT_EPISODE_RUNTIME
from .constants import DEFAULT_FILM_RUNTIME as _DEFAULT_FILM_RUNTIME

# CREATE OR REPLACE (functions) / DROP IF EXISTS + CREATE (triggers, no
# CREATE OR REPLACE TRIGGER before PG14) makes this safe to re-run — needed
# since Base.metadata.create_all() runs it again on every test's fresh schema.
WATCH_MINUTES_TRIGGER_SQL = f"""
-- One row's watch-minutes contribution: film → runtime if completed; tv show
-- → episodes_watched (or total_episodes, if completed with no per-episode
-- count) times runtime. Single source of truth for the aggregate CASE logic,
-- used both by the incremental triggers below and by the manual full-resync
-- utility (recompute_user_watch_minutes).
CREATE OR REPLACE FUNCTION _watch_minutes_contribution(
    p_status text, p_episodes_watched integer, p_media_type text,
    p_runtime_minutes integer, p_total_episodes integer
) RETURNS integer AS $$
DECLARE
    eps integer;
BEGIN
    IF p_media_type = 'film' THEN
        IF p_status = 'completed' THEN
            RETURN COALESCE(p_runtime_minutes, {_DEFAULT_FILM_RUNTIME});
        END IF;
        RETURN 0;
    ELSIF p_media_type = 'tv_show' THEN
        eps := p_episodes_watched;
        IF p_status = 'completed' AND p_episodes_watched = 0 AND p_total_episodes IS NOT NULL THEN
            eps := p_total_episodes;
        END IF;
        RETURN eps * COALESCE(p_runtime_minutes, {_DEFAULT_EPISODE_RUNTIME});
    END IF;
    RETURN 0;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Manual repair utility only — NOT on the trigger hot path. The triggers
-- below maintain total_watch_minutes incrementally; this recomputes one
-- user's total from scratch, for ad-hoc resync if the column is ever
-- suspected to have drifted (e.g. a manual data fix that bypassed triggers).
CREATE OR REPLACE FUNCTION recompute_user_watch_minutes(target_user_id integer)
RETURNS void AS $$
BEGIN
    UPDATE users
    SET total_watch_minutes = COALESCE((
        SELECT SUM(_watch_minutes_contribution(
            mi.status::text, mi.episodes_watched, t.media_type::text, t.runtime_minutes, t.total_episodes
        ))
        FROM media_items mi
        JOIN titles t ON t.id = mi.title_id
        WHERE mi.user_id = target_user_id
    ), 0)
    WHERE id = target_user_id;
END;
$$ LANGUAGE plpgsql;

-- Incremental: looks up the row's title once, computes old/new contribution
-- from OLD/NEW directly, and applies just the difference — O(1), not a scan
-- of the user's library.
CREATE OR REPLACE FUNCTION trg_media_items_watch_minutes() RETURNS trigger AS $$
DECLARE
    v_title_id integer;
    t_media_type text;
    t_runtime integer;
    t_total_episodes integer;
    old_contribution integer := 0;
    new_contribution integer := 0;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_title_id := OLD.title_id;
    ELSE
        v_title_id := NEW.title_id;
    END IF;

    SELECT media_type::text, runtime_minutes, total_episodes
    INTO t_media_type, t_runtime, t_total_episodes
    FROM titles WHERE id = v_title_id;

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_contribution := _watch_minutes_contribution(
            OLD.status::text, OLD.episodes_watched, t_media_type, t_runtime, t_total_episodes
        );
    END IF;
    IF TG_OP IN ('UPDATE', 'INSERT') THEN
        new_contribution := _watch_minutes_contribution(
            NEW.status::text, NEW.episodes_watched, t_media_type, t_runtime, t_total_episodes
        );
    END IF;

    IF TG_OP = 'DELETE' THEN
        UPDATE users SET total_watch_minutes = total_watch_minutes - old_contribution WHERE id = OLD.user_id;
        RETURN OLD;
    ELSIF TG_OP = 'INSERT' THEN
        UPDATE users SET total_watch_minutes = total_watch_minutes + new_contribution WHERE id = NEW.user_id;
        RETURN NEW;
    ELSE
        IF OLD.user_id IS DISTINCT FROM NEW.user_id THEN
            UPDATE users SET total_watch_minutes = total_watch_minutes - old_contribution WHERE id = OLD.user_id;
            UPDATE users SET total_watch_minutes = total_watch_minutes + new_contribution WHERE id = NEW.user_id;
        ELSIF old_contribution IS DISTINCT FROM new_contribution THEN
            UPDATE users SET total_watch_minutes = total_watch_minutes + (new_contribution - old_contribution)
            WHERE id = NEW.user_id;
        END IF;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS media_items_watch_minutes_iud ON media_items;
CREATE TRIGGER media_items_watch_minutes_iud
AFTER INSERT OR DELETE ON media_items
FOR EACH ROW EXECUTE FUNCTION trg_media_items_watch_minutes();

DROP TRIGGER IF EXISTS media_items_watch_minutes_update ON media_items;
CREATE TRIGGER media_items_watch_minutes_update
AFTER UPDATE ON media_items
FOR EACH ROW
WHEN (
    OLD.status IS DISTINCT FROM NEW.status
    OR OLD.episodes_watched IS DISTINCT FROM NEW.episodes_watched
    OR OLD.user_id IS DISTINCT FROM NEW.user_id
)
EXECUTE FUNCTION trg_media_items_watch_minutes();

-- titles: runtime_minutes/total_episodes are shared facts a TMDB refresh can
-- change underneath every user who has that title in their library — this
-- fans out to each of them, but each is still an O(1) delta (uq_user_title
-- means at most one media_items row per (user, title)), not a full recompute
-- of that user's whole library.
-- Set-based, not a per-row PL/pgSQL loop with N individual UPDATE
-- statements: one UPDATE...FROM applies every affected user's delta in a
-- single execution, however many users share this title.
CREATE OR REPLACE FUNCTION trg_titles_watch_minutes() RETURNS trigger AS $$
BEGIN
    UPDATE users
    SET total_watch_minutes = total_watch_minutes + d.delta
    FROM (
        SELECT
            mi.user_id,
            _watch_minutes_contribution(
                mi.status::text, mi.episodes_watched, NEW.media_type::text, NEW.runtime_minutes, NEW.total_episodes
            )
            - _watch_minutes_contribution(
                mi.status::text, mi.episodes_watched, OLD.media_type::text, OLD.runtime_minutes, OLD.total_episodes
            ) AS delta
        FROM media_items mi
        WHERE mi.title_id = NEW.id
    ) AS d
    WHERE users.id = d.user_id AND d.delta != 0;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS titles_watch_minutes_update ON titles;
CREATE TRIGGER titles_watch_minutes_update
AFTER UPDATE ON titles
FOR EACH ROW
WHEN (
    OLD.runtime_minutes IS DISTINCT FROM NEW.runtime_minutes
    OR OLD.total_episodes IS DISTINCT FROM NEW.total_episodes
)
EXECUTE FUNCTION trg_titles_watch_minutes();
"""

WATCH_MINUTES_TRIGGER_TEARDOWN_SQL = """
DROP TRIGGER IF EXISTS titles_watch_minutes_update ON titles;
DROP FUNCTION IF EXISTS trg_titles_watch_minutes();
DROP TRIGGER IF EXISTS media_items_watch_minutes_update ON media_items;
DROP TRIGGER IF EXISTS media_items_watch_minutes_iud ON media_items;
DROP FUNCTION IF EXISTS trg_media_items_watch_minutes();
DROP FUNCTION IF EXISTS recompute_user_watch_minutes(integer);
DROP FUNCTION IF EXISTS _watch_minutes_contribution(text, integer, text, integer, integer);
"""

# app_counters.total_users backs /stats/ranking's percentile denominator
# (routers/stats.py._compute_ranking) and counts CONFIRMED users only (see
# users.email_confirmed) — an unconfirmed/throwaway account must not pad the
# denominator or the "ahead of me" comparison, closing the ranking-inflation
# gap a captcha alone doesn't (bulk hand-registered accounts still pass a
# captcha). COUNT(*) FROM users WHERE email_confirmed has no O(1) shortcut in
# Postgres — MVCC means every row's visibility must be checked, index or not
# — so at large user counts, computing it fresh on every ranking request
# becomes real, unavoidable latency. This keeps a running total instead,
# updated by the same one-row-at-a-time trigger pattern as
# total_watch_minutes: correct by construction, not by an app-level
# increment call that could be missed on some future write path.
#
# Two triggers, not one: INSERT/DELETE (trg_users_count) only ever sees a
# confirmed row on DELETE (a brand-new user is always email_confirmed=false),
# so a second trigger (trg_users_email_confirmed) watches the UPDATE that
# flips the flag — in either direction, since the email-change flow can flip
# a confirmed user back to unconfirmed until the new address is verified.
#
# The (id=1) row is seeded here rather than assumed present, so this stays
# safe to run against a database that hasn't been through the seeding
# migration yet (e.g. Base.metadata.create_all() in tests, which has no
# concept of migration order).
USER_COUNT_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION trg_users_count() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.email_confirmed THEN
            UPDATE app_counters SET total_users = total_users + 1 WHERE id = 1;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.email_confirmed THEN
            UPDATE app_counters SET total_users = total_users - 1 WHERE id = 1;
        END IF;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_users_email_confirmed() RETURNS trigger AS $$
BEGIN
    IF NEW.email_confirmed AND NOT OLD.email_confirmed THEN
        UPDATE app_counters SET total_users = total_users + 1 WHERE id = 1;
    ELSIF OLD.email_confirmed AND NOT NEW.email_confirmed THEN
        UPDATE app_counters SET total_users = total_users - 1 WHERE id = 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

INSERT INTO app_counters (id, total_users)
VALUES (1, (SELECT COUNT(*) FROM users WHERE email_confirmed))
ON CONFLICT (id) DO NOTHING;

DROP TRIGGER IF EXISTS users_count_iud ON users;
CREATE TRIGGER users_count_iud
AFTER INSERT OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION trg_users_count();

DROP TRIGGER IF EXISTS users_email_confirmed_update ON users;
CREATE TRIGGER users_email_confirmed_update
AFTER UPDATE ON users
FOR EACH ROW
WHEN (OLD.email_confirmed IS DISTINCT FROM NEW.email_confirmed)
EXECUTE FUNCTION trg_users_email_confirmed();
"""

USER_COUNT_TRIGGER_TEARDOWN_SQL = """
DROP TRIGGER IF EXISTS users_email_confirmed_update ON users;
DROP FUNCTION IF EXISTS trg_users_email_confirmed();
DROP TRIGGER IF EXISTS users_count_iud ON users;
DROP FUNCTION IF EXISTS trg_users_count();
"""

# titles.rating_sum/rating_count and episode_rating_aggregates back
# /media/ratings, /media/ratings/batch and /media/episode-ratings — each was
# previously a live query over every matching media_items/episode_watches
# row (title_ratings even pulled every individual rating value into Python
# just to sum() them there). Fine at today's scale, but that cost scales
# with "how many people rated this exact title/episode", which is precisely
# the number that grows fastest for a popular title — and worse, it's
# recomputed on every single read, so read traffic on a hot title
# multiplies the cost further. Same fix, same reasoning, as
# total_watch_minutes/total_users above: a running total maintained by an
# O(1)-per-row trigger, so a read is a single indexed point lookup
# regardless of how many ratings feed it.
#
# episode_rating_aggregates has no natural link from episode_watches (which
# only carries media_item_id, season, episode — not title_id), so the
# trigger resolves title_id via one extra lookup into media_items and
# upserts the aggregate row (ON CONFLICT DO UPDATE) — it may not exist yet
# on a title's very first episode rating, unlike titles.rating_sum/count
# which always has a row to update since a media_items row can't exist
# without its title already existing.
RATING_AGGREGATES_TRIGGER_SQL = """
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

RATING_AGGREGATES_TRIGGER_TEARDOWN_SQL = """
DROP TRIGGER IF EXISTS episode_watches_rating_update ON episode_watches;
DROP TRIGGER IF EXISTS episode_watches_rating_iud ON episode_watches;
DROP FUNCTION IF EXISTS trg_episode_watches_rating();
DROP TRIGGER IF EXISTS media_items_rating_update ON media_items;
DROP TRIGGER IF EXISTS media_items_rating_iud ON media_items;
DROP FUNCTION IF EXISTS trg_media_items_rating();
"""
