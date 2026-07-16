"""add user total_watch_minutes ranking cache column

Backing store for the watch-time leaderboard. Kept in sync by a Postgres
trigger on media_items (and on titles, for runtime_minutes/total_episodes
changes) rather than application code remembering to call a recompute
function after every write — the same *_count-drifted-from-the-log incident
that test_normalization.py's ALLOWED_AGGREGATES guard exists to prevent
would apply just as much to an app-level "don't forget to call this" counter,
so the aggregate is instead maintained atomically, in the same transaction
as the row change, by the database itself. See docs/design-decisions.md.

Also adds app_counters (a singleton total_users counter, same
trigger-maintained pattern) — /stats/ranking's percentile denominator would
otherwise be a bare COUNT(*) FROM users on every ranking request, which has
no O(1) shortcut in Postgres regardless of indexing (MVCC visibility must be
checked per row); maintaining it incrementally means the ranking endpoint
never pays for scanning the whole users table just to answer "how many are
there".

The trigger/function SQL itself is imported from xoutaim_backend.db_triggers
rather than inlined here — deliberately not "standalone", unlike this file's
own numeric literals below. It's also registered against each relevant
table's own after_create event (models.py) so it exists in the schema tests
build via create_all(), which never runs this migration; importing one
shared definition is safer than two copies of the trigger SQL drifting
apart, which matters more here than migration self-containment does.

Revision ID: a7c2e9f4b816
Revises: a3d8e2c1b4f7
Create Date: 2026-07-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from xoutaim_backend.db_triggers import (
    USER_COUNT_TRIGGER_SQL,
    USER_COUNT_TRIGGER_TEARDOWN_SQL,
    WATCH_MINUTES_TRIGGER_SQL,
    WATCH_MINUTES_TRIGGER_TEARDOWN_SQL,
)

# revision identifiers, used by Alembic.
revision: str = "a7c2e9f4b816"
down_revision: str | Sequence[str] | None = "a3d8e2c1b4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors DEFAULT_FILM_RUNTIME / DEFAULT_EPISODE_RUNTIME in routers/stats.py —
# kept as a literal here (not read from the app) since the one-time backfill
# below is the exception: it must stay correct standalone, independent of the
# app code as it exists today, unlike the trigger SQL above.
_DEFAULT_FILM_RUNTIME = 110
_DEFAULT_EPISODE_RUNTIME = 40

_AGGREGATE_CASE_SQL = f"""
    CASE
        WHEN t.media_type = 'film' AND mi.status = 'completed'
            THEN COALESCE(t.runtime_minutes, {_DEFAULT_FILM_RUNTIME})
        WHEN t.media_type = 'tv_show' THEN
            (CASE
                WHEN mi.status = 'completed' AND mi.episodes_watched = 0
                     AND t.total_episodes IS NOT NULL
                    THEN t.total_episodes
                ELSE mi.episodes_watched
            END) * COALESCE(t.runtime_minutes, {_DEFAULT_EPISODE_RUNTIME})
        ELSE 0
    END
"""


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("total_watch_minutes", sa.Integer(), nullable=False, server_default="0"))
    # Composite, not single-column: _compute_ranking's rank query is
    # `total_watch_minutes > :own OR (total_watch_minutes = :own AND
    # created_at < :own_created_at)` — the tie-break branch needs created_at
    # in the same index to be answered by an index-only scan instead of an
    # equality lookup followed by an unindexed created_at filter.
    op.create_index("ix_users_total_watch_minutes", "users", ["total_watch_minutes", "created_at"])

    # One-time backfill for existing users. Everything from here on is kept
    # current by the triggers below, not by re-running this aggregation.
    op.execute(
        f"""
        UPDATE users SET total_watch_minutes = COALESCE(sub.total, 0)
        FROM (
            SELECT mi.user_id AS user_id, SUM({_AGGREGATE_CASE_SQL}) AS total
            FROM media_items mi
            JOIN titles t ON t.id = mi.title_id
            GROUP BY mi.user_id
        ) AS sub
        WHERE users.id = sub.user_id
        """
    )

    op.execute(WATCH_MINUTES_TRIGGER_SQL)

    op.create_table(
        "app_counters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_users", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_app_counters_singleton"),
    )
    # USER_COUNT_TRIGGER_SQL seeds row id=1 from COUNT(*) FROM users itself
    # (ON CONFLICT DO NOTHING — safe to also run via create_all() in tests),
    # so no separate backfill step is needed here.
    op.execute(USER_COUNT_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(USER_COUNT_TRIGGER_TEARDOWN_SQL)
    op.drop_table("app_counters")
    op.execute(WATCH_MINUTES_TRIGGER_TEARDOWN_SQL)
    op.drop_index("ix_users_total_watch_minutes", table_name="users")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("total_watch_minutes")
