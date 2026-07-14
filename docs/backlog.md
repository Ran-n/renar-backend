[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/07/11 15:25:11.912794 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Known gaps and follow-ups, not yet scheduled.

## Performance / responsiveness

- **Reduce endpoint latency so the frontend feels snappier.** Audit the
  hot endpoints the UI blocks on (library listing, explore, title/episode
  detail, profile/social) for N+1 queries, missing eager loads, and
  missing indexes; add pagination where responses are unbounded; cache
  rarely-changing lookups (e.g. TMDB-derived metadata) instead of
  recomputing or re-fetching per request. Frontend-side perceived-delay
  work has its own entry in xoutaim-frontend's `docs/backlog.md`.

- **Minimize outside API calls; persist and serve locally.** Treat
  external services (TMDB, YouTube, cover/poster sources) as sources to
  ingest from, not to proxy per request: once metadata, images, or episode
  data have been fetched, store them locally (DB rows, downloaded image
  files) and serve subsequent requests from local data. Only go outside
  when the data is missing or explicitly refreshed, and back remaining
  external calls with a cache and rate-limit-aware retry.

## TV Time import (`routers/imports.py`)

- **Infra failures counted as "skipped".** `_upsert_library_entry`'s broad
  `except Exception` logs a warning and returns `None`, and the caller counts
  that row as `skipped` — indistinguishable from a normal dedupe skip in the
  summary the frontend shows. A DB hiccup mid-import currently surfaces as
  "Import complete ✓, N skipped" instead of an error. Add a separate `errors`
  counter to the summary and surface it in the import view.

- **Transient TMDB failures permanently degrade an entry, and re-import can't
  heal it.** If a TMDB lookup fails (rate limit, outage) the row imports
  unmatched (no `tmdb_id`, poster, or episode counts). A later re-import
  resolves fine but falls back to title-matching against the existing
  (tmdb_id-less) entry: if titles match it reconciles without ever backfilling
  `tmdb_id`/poster onto the `Title`, so it stays degraded forever; if titles
  differ, a duplicate entry is created instead. No retry/backoff on 429s
  either, and 8 concurrent workers make bursts more likely. Fix should
  backfill `tmdb_id`/metadata onto the `Title` during reconcile when the
  incoming row resolved but the stored `Title` didn't.

- **Server restart mid-import fails silently, and the frontend reports it as
  success.** Progress lives only in the in-memory `_progress` dict, and the
  job runs on a daemon thread. A restart mid-import loses the job (safe to
  re-run) but `/import/tvtime/status` then returns `{"stage": "Never run",
  "finished": true}` with no error — which the frontend's poll loop
  ([import_view.py](../../xoutaim-frontend/src/xoutaim_frontend/views/import_view.py))
  renders as "Import complete ✓" with all-zero counts.

- **Minor: concurrent reconciles of the same entry are last-write-wins.**
  Two rows racing to reconcile into the same `LibraryEntry` aren't
  serialized — harmless today since both reconcile functions are monotonic
  (favorite only flips true, rating only fills when empty), but worth a note
  if reconcile logic grows less monotonic later.

- **Minor: `_progress` entries are never pruned.** Negligible memory; clears
  on process restart. Not worth fixing unless it becomes visible.

## Features

- **Premium-only ranking/badges (TV Time-style).** Give premium users a
  ranking/leaderboard and a set of unlockable badges based on watch activity.
  Note this is a real departure from the current badge design, which is
  explicitly "one derived badge, never a stored list" (see
  `docs/design-decisions.md`); a badge/achievement set implies new tables
  (e.g. `Achievement`, per-user unlock rows) and a ranking implies either a
  live-computed or cached/precomputed leaderboard. `routers/stats.py`
  already computes the per-user signals a ranking/badge engine would need
  (episodes/films watched, watch streaks, ratings, completions, genre
  breakdown) — no leaderboard table exists yet. Needs scoping: global vs.
  friends-only ranking, fixed badge set vs. tiers, how it interacts with the
  existing premium/verified badge slot.

## Infrastructure

- **psycopg3 stale prepared plans after live schema changes.** psycopg3
  auto-prepares statements reused ~5+ times per connection. DDL that alters
  or recreates tables against a pool with existing prepared plans triggers
  `cached plan must not change result type` on the next query using that
  connection. Tests are fixed via `engine.dispose()` in conftest's
  `_fresh_db` fixture. **Production implication: restart/recycle the app
  after running Alembic migrations**, so no pooled connection holds a plan
  against pre-migration table shapes.
