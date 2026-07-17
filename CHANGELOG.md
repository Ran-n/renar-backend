[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:51.980396 )
[//]: # (+ Revised: 	2026/07/17 12:35:05.862800 )
[//]: # ( ---------------------------------------------------------------------- )

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Test coverage for `routers/books.py` (`tests/test_books.py`), matching the mocking
  approach already used for `routers/youtube.py`

### Changed

- Consolidated `DEFAULT_FILM_RUNTIME` / `DEFAULT_EPISODE_RUNTIME`, previously duplicated
  in `db_triggers.py` and `routers/stats.py`, into a single `src/xoutaim_backend/constants.py`
  source of truth; `routers/social.py` now imports from there directly instead of via
  `routers/stats.py`

## [0.3.0] - 2026-07-17

### Added

- `site_settings` singleton table: DB-backed runtime settings for all
  anti-abuse tunables and registration flags, editable live from
  `<ADMIN_PATH>/settings` (no restart needed) — see `docs/anti-abuse.md`
  and `src/xoutaim_backend/site_settings.py`
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
- Admin panel (`routers/admin.py`, HTML behind HTTP Basic): user manager
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
