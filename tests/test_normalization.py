#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/08/17 17:05:34.076782

Schema normalization guard: fails CI the moment a denormalization sneaks
back into the models.

Each rule below is a mechanical proxy for one of the classic normal forms
— SQLAlchemy metadata carries no functional-dependency information, so
these are structural approximations, not proofs, but each maps onto a
specific textbook form:

- `test_string_columns_do_not_look_multivalued` — 1NF (atomic values: a
  plural-named string column is the classic delimiter-joined-list smell).
- `test_id_columns_are_foreign_keys` — entity integrity: an `*_id` column
  is either a real reference (FK) or it isn't identity at all.
- `test_no_copied_columns_across_foreign_keys` — 2NF/3NF/BCNF: a column
  whose name matches a column on a table reachable through one of this
  table's own FKs is the structural signature of a value that is copied
  from (or derivable through) another table's row rather than functionally
  dependent on this table's own key alone. Concretely this is a partial
  dependency (2NF) when the FK is one component of a composite candidate
  key here, and a transitive dependency (3NF/BCNF) when it isn't — the
  same check catches both because both are "this attribute depends on
  something reachable via one FK, not on the whole of this table's key."
- `test_no_unregistered_aggregate_columns` — a stored aggregate is
  functionally dependent on the rows it summarizes, not on this table's
  own key; the normalized form derives it in the query instead. Not one
  of the numbered normal forms by itself, but the same "derive, don't
  duplicate" principle they all share.
- `test_regression_pins` — no theory, just pinned regressions: every
  denormalization this schema has already been cured of once.

If you hit a failure here, normalize the schema (association table, FK to
the owning table, derive the value in the query) instead of widening the
allowlists; a new entry needs a justification string explaining why the
value is independent data, a deliberately bounded counter, or a
same-named-but-different fact — not a copy of another row.
"""

import re

from sqlalchemy import String, Text

from renar_backend.database import Base

# Columns that legitimately hold a number that *looks* aggregated. Each entry
# documents why it is not derivable from (or is allowed to summarize) other
# rows. Deleting rules or adding entries here is a design decision — record it
# in docs/design-decisions.md.
ALLOWED_AGGREGATES: dict[str, str] = {
    "endpoint_stats.count": "bounded upsert counter by design: one row per (method, route, user), never per request",
    "request_days.count": "bounded upsert counter by design: one row per (user, day), never per request",
    "strikes.count": "offense counter, one row per IP by design so abuse state can never grow unbounded",
    "media_items.episodes_watched": (
        "user-asserted coarse progress: independent data when no episode_watches rows exist; "
        "when they do exist, _sync_progress is the single write path that derives it"
    ),
    "titles.total_episodes": "fact about the show from TMDB, not a count of our rows",
    "titles.total_seasons": "fact about the show from TMDB, not a count of our rows",
    "images.size_bytes": "fact about the stored file, not a count of rows",
    "users.total_watch_minutes": (
        "ranking leaderboard cache — unlike login_count (the counter that "
        "drifted and motivated this rule), this is maintained by a Postgres "
        "trigger on media_items/titles (migration a7c2e9f4b816), atomically "
        "in the same transaction as the row that changed it, not by "
        "application code remembering to call a recompute function; see "
        "docs/design-decisions.md"
    ),
    "app_counters.total_users": (
        "ranking leaderboard denominator cache, same trigger-maintained "
        "pattern (and same justification) as users.total_watch_minutes — "
        "COUNT(*) FROM users has no O(1) shortcut in Postgres regardless of "
        "indexing, so this avoids scanning the whole users table on every "
        "ranking request; see docs/design-decisions.md"
    ),
    "titles.rating_count": (
        "Renar community-rating cache for /media/ratings, same trigger-"
        "maintained pattern as users.total_watch_minutes (migration "
        "6eae4e5ba1c0) — avoids live-aggregating every media_items.rating "
        "for a title on every read; see docs/design-decisions.md"
    ),
    "episode_rating_aggregates.rating_count": (
        "per-episode counterpart to titles.rating_count, same trigger-"
        "maintained pattern, for /media/episode-ratings — see "
        "docs/design-decisions.md"
    ),
}

# FK-looking columns that intentionally carry no ForeignKey.
ALLOWED_FKLESS_ID_COLUMNS: dict[str, str] = {
    "titles.tmdb_id": "external identity in TMDB's keyspace, not a row of ours",
}

# Columns flagged by test_no_copied_columns_across_foreign_keys that are not
# actually copies: same column name as one on a table reachable via an FK,
# but a different fact by design. Keyed by (qualified_column, ref_table).
# Adding an entry is a design decision and belongs in docs/design-decisions.md.
ALLOWED_COPIED_COLUMNS: dict[tuple[str, str], str] = {
    ("episode_watches.rating", "media_items"): (
        "a per-episode rating, independent of media_items.rating (the show's "
        "overall rating) — same column name, unrelated fact"
    ),
    ("comment_likes.user_id", "comments"): (
        "the user who liked the comment, not comments.user_id (its author) — "
        "a second, unrelated FK to users that happens to share the name"
    ),
    ("comment_reports.user_id", "comments"): (
        "the reporter, not comments.user_id (the comment's author) — a "
        "second, unrelated FK to users that happens to share the name"
    ),
    ("notifications.user_id", "media_items"): (
        "the recipient. media_item_id is nullable (system notifications carry "
        "none), so user_id can't be derived through it alone and must be "
        "stored independently; when both are set they're kept in agreement "
        "by construction in routers/notifications.py, not by a query-time join"
    ),
    ("episode_rating_aggregates.rating_sum", "titles"): (
        "a per-episode rating total, independent of titles.rating_sum (the "
        "show's overall rating total) — same column name, unrelated fact, "
        "same reasoning as episode_watches.rating vs media_items.rating above"
    ),
    ("episode_rating_aggregates.rating_count", "titles"): (
        "a per-episode rating count, independent of titles.rating_count — "
        "same column name, unrelated fact, same reasoning as "
        "episode_watches.rating vs media_items.rating above"
    ),
}

# Structural/provenance columns that recur on almost every table by
# convention and are never a copy of another row's value: a row's own
# surrogate key and its own creation/update timestamp are about *this* row.
_STRUCTURAL_COLUMNS = {"id", "created_at", "updated_at"}

_AGGREGATE_PATTERN = re.compile(r"(^count$|_count$|^total_|^num_|_watched$|_bytes$)")


def _all_columns():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            yield table, column, f"{table.name}.{column.name}"


def test_id_columns_are_foreign_keys():
    """Every *_id column must reference its table — identity by FK, never by
    duplicated attribute columns."""
    offenders = [
        qualified
        for table, column, qualified in _all_columns()
        if column.name.endswith("_id") and not column.foreign_keys and qualified not in ALLOWED_FKLESS_ID_COLUMNS
    ]
    assert not offenders, (
        f"columns look like foreign keys but declare none: {offenders} — "
        "point them at the owning table with ForeignKey(), or register them "
        "in ALLOWED_FKLESS_ID_COLUMNS with a justification"
    )


def test_no_copied_columns_across_foreign_keys():
    """2NF/3NF/BCNF, mechanized: for every column C on table T that is a
    foreign key to table R, T must carry no *other* column whose name also
    exists on R (ignoring structural columns). Such a column is either
    derivable from the FK alone (a partial dependency on one component of a
    composite key — 2NF) or copied from a row reachable through the FK
    rather than dependent on T's own key (a transitive dependency — 3NF/
    BCNF); either way it isn't functionally dependent on T's own key alone.
    """
    offenders = []
    for table in Base.metadata.tables.values():
        own_columns = {c.name for c in table.columns} - _STRUCTURAL_COLUMNS
        for column in table.columns:
            for fk in column.foreign_keys:
                ref_table = fk.column.table
                if ref_table is table:
                    continue  # self-referential FK (e.g. comments.parent_id)
                ref_columns = {c.name for c in ref_table.columns} - _STRUCTURAL_COLUMNS
                for name in (own_columns - {column.name}) & ref_columns:
                    qualified = f"{table.name}.{name}"
                    if (qualified, ref_table.name) in ALLOWED_COPIED_COLUMNS:
                        continue
                    offenders.append(f"{qualified} (via FK {table.name}.{column.name} -> {ref_table.name})")
    assert not offenders, (
        f"columns duplicate an attribute reachable through one of their table's own FKs: {offenders} — "
        "derive the value through the FK instead of storing a copy, or register it in "
        "ALLOWED_COPIED_COLUMNS with a justification for why it's a different fact"
    )


def test_no_unregistered_aggregate_columns():
    """A column named like a count/total is usually a cache of other rows —
    derive it in the query instead of storing it."""
    offenders = [
        qualified
        for table, column, qualified in _all_columns()
        if _AGGREGATE_PATTERN.search(column.name) and qualified not in ALLOWED_AGGREGATES
    ]
    assert not offenders, (
        f"columns look like stored aggregates: {offenders} — derive the value "
        "from the rows it summarizes, or register it in ALLOWED_AGGREGATES "
        "with a justification"
    )


def test_string_columns_do_not_look_multivalued():
    """1NF: one value per column. A plural-named string column is the classic
    smell of a delimiter-joined list (titles.genres once held 'Drama, Crime');
    model those as an association table."""
    allowed_plural = {
        "media_items.notes",  # one free-text blob, not a list of values
    }
    offenders = []
    for _table, column, qualified in _all_columns():
        if not isinstance(column.type, (String, Text)) or qualified in allowed_plural:
            continue
        # plural nouns: name ends in s but not a known singular-ish suffix
        if re.search(r"(?<![su'])s$", column.name) and not column.name.endswith(("status", "address")):
            offenders.append(qualified)
    assert not offenders, (
        f"string columns with plural names: {offenders} — if these hold "
        "multiple values in one string, split them into a child/association "
        "table; if the name is just misleading, rename the column"
    )


def test_regression_pins():
    """Every denormalization this schema has already been cured of, pinned so
    it cannot quietly return."""
    tables = Base.metadata.tables

    # genres are rows linked through title_genres, not a string on titles
    assert "genres" in tables and "title_genres" in tables
    assert "genres" not in tables["titles"].columns
    assert {c.name for c in tables["title_genres"].primary_key.columns} == {"title_id", "genre_id"}
    assert any(c.unique or c.index for c in [tables["genres"].columns["name"]])

    # comments reference the titles table, they do not re-describe title identity
    comment_cols = tables["comments"].columns
    assert "title_id" in comment_cols and comment_cols["title_id"].foreign_keys
    for banned in ("media_type", "tmdb_id", "title_key"):
        assert banned not in comment_cols, f"comments.{banned} duplicates Title identity"

    # a reply's scope is a fact about its thread root, not itself — only a
    # root comment (parent_id IS NULL) may carry title_id, so the column
    # must be nullable (see comment_threads.resolve_root_scope)
    assert comment_cols["title_id"].nullable, "comments.title_id must stay nullable (only roots carry scope)"

    # user usage counters are derived from login_events / request_days / endpoint_stats
    user_cols = tables["users"].columns
    for banned in ("login_count", "last_login_at", "request_count"):
        assert banned not in user_cols, f"users.{banned} duplicates the event tables"
