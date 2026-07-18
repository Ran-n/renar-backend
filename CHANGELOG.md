[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:51.980396 )
[//]: # (+ Revised: 	2026/07/18 16:51:22.083537 )
[//]: # ( ---------------------------------------------------------------------- )

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-07-18

### Added

- Admin panel: `trust_proxy_headers`/`exempt_ips` are now live-editable from
  `<ADMIN_PATH>/settings` (Network & exemptions section), backed by the
  `site_settings` DB row instead of requiring an `.env` edit + restart

### Changed

- Project renamed from Xoutaim to Renar: package `xoutaim_backend` →
  `renar_backend`, PyPI/project name `xoutaim-backend` → `renar-backend`,
  `INTERNAL_SERVICE_SECRET` counterpart env var on the frontend
  `XOUTAIM_INTERNAL_SECRET` → `RENAR_INTERNAL_SECRET`. Subdomain decided as
  `renar.breren.com` (see `docs/backlog.md`, Infrastructure section)

### Fixed

- Comments N+1: `routers/comments.py`'s `_comment_out` walked
  `Comment.author`/`.likes`/`.reports`/`.replies` per node, firing on the order
  of hundreds to thousands of queries for a page of nested comments. Added
  `social/comment_threads.load_thread()` (one recursive CTE + three
  `selectinload`s) so a whole thread loads in a fixed number of queries
  regardless of size/depth
- `routers/social.py`'s `activity_feed` wasn't eager-loading `title_ref`/
  genres/custom images, causing a lazy load per row (up to 50/request)
- Missing composite indexes on `Notification`: replaced the low-cardinality
  standalone `read` index with `(user_id, read)` and `(user_id, created_at)`
  (migration `45a9dba29ff9`), matching `LibraryEntry`'s existing pattern

## [0.4.0] - 2026-07-17

### Added

- Test coverage for `routers/books.py` (`tests/test_books.py`), matching the mocking
  approach already used for `routers/youtube.py`
- `periodic_task_runs` table (migration `f2a7c9d1b3e4`, extended by `a4e8d0c62f17`
  and `b7c3f5a91d02`): per-task `enabled` flag, `interval_minutes`, and last-run
  status (`ok` / `error` / `skipped`, started/finished timestamps, a free-text
  detail) — replaces the old grouped `site_settings` toggles with one independently
  controllable row per background task
- `task_runs.py`: registry of background tasks (`episode_check`,
  `episode_history_sync`, `film_check`, `strike_cleanup`), each with its own
  media-type `group` (TV Shows / Films / Security) for the admin UI; short-TTL
  cached `is_enabled()` / `get_interval_minutes()` reads (same pattern as
  `site_settings.current()`) and `set_enabled()` / `set_interval_minutes()` /
  `record_run()` writes
- Admin panel: **Periodic Tasks** tile and page (`GET <ADMIN_PATH>/periodic-tasks`),
  replacing the toggle-only section that used to live on Site Settings — cards
  grouped by media type, each task independently enabled/disabled
  (`POST .../periodic-tasks/toggle`) and rescheduled
  (`POST .../periodic-tasks/interval`), showing live status: last run, result
  detail, and an estimated next run

### Changed

- Consolidated `DEFAULT_FILM_RUNTIME` / `DEFAULT_EPISODE_RUNTIME`, previously duplicated
  in `db_triggers.py` and `routers/stats.py`, into a single `src/renar_backend/constants.py`
  source of truth; `routers/social.py` now imports from there directly instead of via
  `routers/stats.py`
- Admin Invite Codes page (`routers/admin/`): revoked status pill now uses a distinct
  color instead of gray, newly generated codes are copied to the clipboard automatically,
  and the invite table has a refresh button matching the Users page pattern
- Admin Invite Codes page: the "just generated" banner now auto-hides itself after 8s;
  the table has a search box + status chips (client-side filter) and sortable columns
  (click a header to sort, click again to reverse); a permanent **Delete** action
  (`POST <ADMIN_PATH>/invites/{id}/delete`) sits alongside the existing soft **Revoke**
  — nothing references `invite_codes.id` as a foreign key, so the delete is a plain
  hard delete with no cascade concerns
- Admin Invite Codes page: Revoke, Restore, and Delete are now visually distinct
  (`.btn-warn` amber / `.btn-good` green / `.btn-purge` red) instead of all three
  sharing the red "destructive" style; added a **Restore** action
  (`POST <ADMIN_PATH>/invites/{id}/restore`) that clears the `revoked` flag without
  otherwise touching the code (an already-expired code stays expired)
- `invite_codes.created_by_admin`: admin-panel-generated invites now record the
  HTTP Basic admin's username as plain text, since that auth is a single
  env-configured credential with no `users.id` row to point `created_by_user_id`
  at — the Created by column previously showed "—" for every admin-created code
  (`models.py`, `routers/admin/`, migration `23dd41789cea`)
- `notifier.run_periodic()` split from one shared loop into three independent
  per-task loops (`episode_check`, `episode_history_sync`, `film_check`), each
  sleeping its own admin-configurable interval instead of one shared poll period
  — pausing or rescheduling one task no longer affects the others
- `security._cleanup_old_strikes` reads its run interval from `task_runs`
  (admin-editable) instead of a hardcoded 1-hour gate
- Admin Site Settings page (`routers/admin/settings.py`): periodic-task toggles
  removed (moved to the new Periodic Tasks page); links there instead

### Removed

- `EPISODE_CHECK_MINUTES` env var / `Settings.episode_check_minutes` — replaced
  by per-task, admin-editable intervals (`periodic_task_runs.interval_minutes`)
- `site_settings.episode_check_enabled` / `film_check_enabled` / `bans_check_enabled`
  columns (migration `a4e8d0c62f17`) — replaced by `periodic_task_runs.enabled`,
  one independent flag per task instead of three flags shared across four tasks

### Fixed

- Admin dashboard (`routers/admin/dashboard.py`): the tile-grid landing page lost
  its own `.page { max-width: 860px }` override when `routers/admin.py` was split
  into the `routers/admin/` package — the dashboard picked up no width constraint
  at all and the tiles stretched edge-to-edge across the full viewport instead of
  a centered column, with the icon+text layout flipped from stacked to side-by-side;
  restored the original narrow centered layout and vertical tile card
- Admin Invite Codes page: the expiry chip presets (`24 hours`, `7 days`, `30 days`,
  custom) sent the browser's local wall-clock digits for `expires_at`, which the
  server then stored as if they were already UTC (`create_invite` in `routers/admin/invites.py`)
  — codes expired off-by-the-admin's-UTC-offset instead of the chosen duration from
  creation; the form now converts to a true UTC instant before submitting
- Admin Invite Codes page: auto-copy-on-generate silently did nothing because
  `navigator.clipboard` requires a secure context (https/localhost) and the failure
  was swallowed; copy now falls back to an `execCommand('copy')` textarea trick when
  the Clipboard API isn't usable, shared by both the auto-copy and the manual
  per-row Copy buttons

## [0.3.0] - 2026-07-17

### Added

- `site_settings` singleton table: DB-backed runtime settings for all
  anti-abuse tunables and registration flags, editable live from
  `<ADMIN_PATH>/settings` (no restart needed) — see `docs/anti-abuse.md`
  and `src/renar_backend/site_settings.py`
- Admin panel: **Site Settings** tile and page (`GET/POST <ADMIN_PATH>/settings`)
  with toggle controls for registration mode and number inputs for every
  rate-limit/ban threshold
- Admin panel: **Invite Codes** tile and page (`GET/POST <ADMIN_PATH>/invites`);
  generates 32-char random codes with configurable max-uses (1/5/10/25/unlimited/custom)
  and optional expiry; revoke-on-page action marks a code `revoked = true`
- `invite_codes` table: per-code use counting with `FOR UPDATE` serialization
  on concurrent registrations
- `POST /auth/register`: invite-code validation when `site_settings.invite_only`
  is `true` — rejects missing, revoked, expired, or fully-used codes;
  increments `uses` in the same transaction as user creation
- `GET /auth/registration-status` — unauthenticated; returns `registration_open`
  and `invite_only` so the signup screen can decide whether to render an
  invite-code field before the user submits
- `RegistrationStatus` schema (narrow public view of two `site_settings` fields)
- Periodic-task toggles in `site_settings`: `episode_check_enabled`,
  `film_check_enabled`, `bans_check_enabled` — admin can pause any background
  task without code changes; `notifier.py` and `security.py` check these
  before each run
- `backend_version()` in `main.py`: reads installed package metadata on startup,
  falls back to `pyproject.toml` for source checkouts; `app.version` is now
  live rather than a hardcoded string
- `UsageTrackingMiddleware` is now added before `AbuseGuardMiddleware` so
  banned/flooded requests never reach usage tracking (previously reversed)
- Responsive CSS (`_RESPONSIVE_CSS`) and `color-scheme: dark` applied to all
  admin panel pages; native form chrome (date pickers, scrollbars) follows
  the OS dark palette
- `_fmt_ts` reformatted to day-month-year ("16 Jul 2026 HH:MM") for readability
- Migration `b9c3e1f84a2d`: create `site_settings` and `invite_codes` tables
- Migration `ae65f1be8d32`: make `invite_codes.max_uses` nullable (unlimited-use codes)
- Migration `c1e6a4f92d38`: add `episode_check_enabled`, `film_check_enabled`,
  `bans_check_enabled` columns to `site_settings`

### Changed

- Anti-abuse tunables (`rate_limit_per_minute`, `flood_ban_per_minute`,
  `auth_rate_limit_per_minute`, `register_per_hour_per_ip`,
  `login_backoff_threshold`, `login_backoff_account_threshold`,
  `login_backoff_minutes`, `probe_ban_threshold`, `probe_window_minutes`,
  `ban_minutes`, `strike_ban_threshold`) and registration flags
  (`registration_open`) moved from `.env`-only to the `site_settings` DB row;
  `.env` values are now **seed defaults** for fresh deployments only
- `REGISTRATION_OPEN` removed from `.env.example` (handled via admin panel now)
- Rate-limit/ban env vars removed from `.env.example`; replaced with a comment
  pointing to `<ADMIN_PATH>/settings`
- `/svc/bans` docstring clarifies the periodic refresh semantics: only
  permabans are merged on the long-interval re-pull (not temp bans)
- `docs/environment-variables.md`: anti-abuse tunables marked as seed-default-only
- `docs/anti-abuse.md`: DB-backed runtime settings and invite-only registration
  sections added; temp-ban vs permaban periodic-sync rationale expanded
- Registration rejection log lines now include which field clashed
  (username vs email) and the existing user's id

### Fixed

- `invite_codes.max_uses` created as `NOT NULL` in migration `b9c3e1f84a2d`
  then immediately corrected to nullable in `ae65f1be8d32`; the model has no
  Python-side default so callers that pass explicit `None` (unlimited) are
  not silently overridden at flush time

## [0.2.0] - 2026-07-16

### Added

- Premium leaderboard/ranking (`GET /stats/ranking`, `GET /stats/ranking/metrics`):
  pluggable per-metric rankings (starts with total watch time) with
  percentile rank against `app_counters.total_users`
- `users.total_watch_minutes` and `app_counters.total_users` — trigger-maintained
  aggregates backing the ranking endpoints (see `docs/design-decisions.md`)
- `users.has_seen_welcome`, settable via `PATCH /auth/profile`; admin can reset it
  per user (`POST /admin/users/{id}/reset-onboarding`) to re-show onboarding
- `GET /media` pagination (`limit`, `offset`) and a `favorites_only` filter
- Composite index on `media_items (user_id, updated_at)` for library pagination
- Anti-abuse system (`security.py`): honeypot paths, unknown-route probe
  detection, per-IP rate limiting/flood bans, per-account login backoff,
  and persisted repeat-offender strikes that escalate a temporary ban into
  a permanent one (`strikes` / `banned_ips` tables) — see
  `docs/anti-abuse.md` and `docs/environment-variables.md`
- Admin panel (`routers/admin/`, HTML behind HTTP Basic): user manager
  with per-user usage stats, comment manager, ban/strike management
- `GET /media/ratings` (community average rating) and
  `POST /media/{id}/rewatch` (log a rewatch of an item or one episode)
- Per-episode comment scoping alongside the existing per-title threads
- Book support end-to-end (`routers/books.py`, Open Library proxy)
- TVDB fallback lookup (`TVDB_API_KEY`) for TV Time import matching when
  the TMDB crosswalk misses
- `tests/` — pytest suite covering every endpoint's happy and error paths
  against a throwaway SQLite database
- `docs/` — environment variable reference and anti-abuse write-up

### Changed

- Split `media_items` into `titles` (shared metadata) and `library_entries`
  (per-user tracking state), with `WatchEvent` for rewatch history
- Comment payloads include the author's avatar

### Fixed

- Unique constraint on media item identity to prevent duplicate titles
