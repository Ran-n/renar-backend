[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:51.980396 )
[//]: # (+ Revised: 	2026/07/16 09:54:29.868949 )
[//]: # ( ---------------------------------------------------------------------- )

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
