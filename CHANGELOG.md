[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:51.980396 )
[//]: # (+ Revised: 	2026/08/20 17:17:27.582996 )
[//]: # ( ---------------------------------------------------------------------- )

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.16.0] - 2026-08-20

### Added

- `Title.release_date` exposed on `TitleOut` and `LibraryEntryOut` (via a new
  `LibraryEntry.release_date` passthrough), so a not-yet-released movie/show
  added to the library can show its release date — was already stored, just
  never returned to clients.
- `logs/renar-backend-errors.log`: a second rotating log file capturing only
  WARNING+ records (including unhandled-request-exception tracebacks), so a
  crash/error check doesn't mean scanning the full log's routine noise.

## [0.15.0] - 2026-08-20

### Fixed

- `list_media`'s `order_by=last_watched` (Home's Watch Next list):
  `_unwatched_aired_episode_clause()`'s nested `EXISTS` wasn't correlated to
  the outer `LibraryEntry` row, so SQLAlchemy silently cross-joined a fresh,
  uncorrelated `media_items` into that subquery instead of matching the
  specific item — turning "has *this* item's episode been watched" into
  "has *any* item's same season/episode number been watched by anyone".
  In a large library that matched almost everywhere, so nearly every
  in-progress show was wrongly treated as fully caught up and dropped from
  Home. Fixed with an explicit `.correlate(LibraryEntry, Episode)` on the
  inner `EXISTS`.

### Security

- `/svc/bans` and `/svc/strikes` (the internal-secret-guarded endpoints
  `renar_backend.routers.svc` exposes so the frontend's anti-abuse guard can
  share ban state) now track repeated wrong-secret attempts per IP and
  escalate through the same `strike_and_maybe_ban`/`permaban` path a probing
  scanner would hit. Previously these were exempt from
  `AbuseGuardMiddleware`'s probe-scanner ban entirely: the route is real (it
  always resolves and 404s by design, to hide whether the secret was just
  wrong or the route doesn't exist), so `_matches_no_route` never flagged it
  — a caller could hammer the secret indefinitely with no consequence short
  of the very high flood-ban threshold. Callers in `site_settings.exempt_ips`
  (127.0.0.1/::1 by default) are skipped entirely, so a misconfigured local
  deployment retrying with a stale secret can never end up banning the
  machine it's running on.

### Added

- `/tmdb/search`, `/tmdb/trending`, and `/tmdb/popular` now fall back to
  Renar's own catalog (substring title match / library-adds ranking) when
  TMDB itself is unreachable (502/503/504), instead of failing outright.
  A genuine "not found" (404) still surfaces as-is — only true TMDB
  outages trigger the fallback. Limited to titles already tracked by
  someone; discovering a title nobody's added yet still requires TMDB.
- `docs/terms-of-service.md`: draft Terms of Service, matching
  `docs/privacy-policy.md`'s DRAFT status and cross-linked with it.
  Covers eligibility/age, accounts, acceptable use, user content, a
  copyright/takedown contact path, TMDB attribution, premium, and
  liability — still needs `[EFFECTIVE DATE]`/`[HOSTING PROVIDER]`/
  `[JURISDICTION]`/`[GOVERNING LAW]` filled in and a legal review before
  publishing.

### Changed

- `docs/backlog.md`: replaced the stale "no privacy policy or ToS exist"
  item with an accurate "drafted but not published" one; added
  `[Blocking for 1.0]` items for the still-missing TMDB logo image (the
  required attribution text now ships in renar-frontend 0.17.4's new Legal
  screen, but not the logo) and for the missing DMCA/takedown process for
  user-submitted content; noted merchant-of-record/VAT/PCI scope on the
  existing premium-payments item.

## [0.14.0] - 2026-08-19

### Added

- `Title` now caches `imdb_id` and `wikidata_id`, synced from TMDB's
  `external_ids` alongside the existing details fetch (no extra API
  call) — groundwork for a future external ratings source (OMDb) and
  per-language Wikipedia links, tracked in `docs/backlog.md`.
- `Title.tvdb_id` is now also refreshed from that same TMDB payload on
  every details sync (previously only ever set via the TV Time import's
  TVDB fallback), collision-guarded against its unique index the same
  way `catalog/titles.py`'s `backfill_title_tvdb_id` already is.
- TheTVDB is now a genuine fallback *identity*, not just a name source for
  a retried TMDB search: when a show's TMDB match fails through every
  avenue (crosswalk, TVDB-name retry, plain title search) and
  `TVDB_API_KEY` is configured, the show is tracked under `Title.tvdb_id`
  with poster, overview, status, runtime, and episode list sourced
  directly from TheTVDB instead of sitting fully blank. TMDB always wins
  the moment it resolves — see `docs/design-decisions.md`.
- `PATCH /media/{id}` accepts an optional `tmdb_id` to manually relink an
  unmatched library entry (`_relink_tmdb` in `routers/media.py`) — the
  backend half of the frontend's "Link to catalog" dialog shipped in
  renar-frontend 0.17.0.
- `unmatched_title_retry`: a periodic background task (`task_runs.py` /
  `social/notifier.py`, every 6h by default) that re-attempts a TMDB match
  for every shared `Title` still unmatched, regardless of which user's
  import created it or whether they ever import again.
- `tmdb_get` now retries a 429/500/502/503/504 or network error up to 3
  attempts in place (honoring `Retry-After`, capped at 8s) before raising,
  instead of permanently degrading the row on a transient failure.
- Expanded test suite: new pytest markers (`integration`, `smoke`,
  `regression`, `contract`, `property`, `snapshot`, `security`, `load`,
  `mutation`, `fuzz`) covering real-process boot, property/fuzz-driven
  validation, snapshot regression, SAST + dependency scanning (bandit,
  pip-audit), and headless load testing (locust); see `README.md` for how
  to select each.

### Fixed

- TV Time import reconciliation now keys the "already in library" lookup
  on the raw source name instead of the TMDB-resolved title — a later
  re-import that resolves a match TMDB's title text differs from (language,
  punctuation, capitalization) was silently creating a duplicate
  `LibraryEntry` instead of healing the earlier unmatched row.

## [0.13.0] - 2026-08-18

### Added

- `GET /auth/me` now returns `grace_days_remaining` for unconfirmed
  accounts (`null` once confirmed), so the frontend can show the
  account's actual remaining grace period instead of a static default.

### Fixed

- `GET /media?status_filter=watching&order_by=last_watched` ("Watch
  Next"): a tv_show fully caught up on everything aired so far no
  longer lingers in the list — it now drops out until a new episode
  actually airs. Shows with no synced episode data, and films (which
  have no episode concept), are never affected by this rule.
- Same endpoint: a show with a genuinely new unwatched episode (aired
  after the show's own `last_watched_at`) now bubbles to position #2,
  right after whatever the user most recently actively watched, instead
  of sorting purely by last-watched time. An old backlog episode the
  user simply hasn't gotten to yet does not trigger this bump.

## [0.12.0] - 2026-08-17

### Added

- `GET/POST /comments` responses now include `seen_by_author` and
  `author_rating` per comment — the commenter's own watch state and 1-100
  grade for the thread's title/episode, resolved from their own library
  entry (`LibraryEntry.last_watched_at`/`.rating`) or, for an episode-
  scoped thread, their `EpisodeWatch` row for that exact episode
  (`comments.py`'s `_build_watch_info`, computed once per request off
  every commenter in the thread rather than per comment). Powers the
  frontend's comment share card, which shows a "seen" glyph and a small
  grade pill next to the commenter's name.

### Changed

- `/media/ratings`, `/media/ratings/batch` and `/media/episode-ratings`
  (the Renar community-average badges) now read from stored running
  totals — `titles.rating_sum`/`rating_count` and the new
  `episode_rating_aggregates` table — instead of recomputing the average
  over every individual rating on each call. Maintained incrementally by
  a Postgres trigger (`db_triggers.py`, migration `6eae4e5ba1c0`,
  backfilled from existing data) so a read is an O(1) indexed lookup
  regardless of how many people have rated a title, and the total can't
  drift since nothing can change a rating without the trigger running in
  the same transaction.

## [0.11.0] - 2026-08-11

### Added

- `POST /media/ratings/batch`: Renar average+count for up to 100 `tmdb_ids`
  at once (`RatingsBatchRequest`, one grouped `GROUP BY Title.tmdb_id`
  query), alongside the existing single-title `GET /media/ratings` —
  Explore's result grid needs one rating per card without a request per
  card.
- `GET /media/{id}/rewatch-events` / `DELETE /media/{id}/rewatch-events/{event_id}`:
  list (newest first) or remove one specific `WatchEvent` row, instead of
  only being able to undo the *latest* rewatch via the existing
  `POST/DELETE .../rewatch`. No schema change — these are new read/delete
  views onto rows that already existed.
- `User.countdown_colors` (migrations `e2c8a4f1d936`, `a4d8e1f39c62`): the
  Upcoming countdown pill's premium color override is now a JSONB map keyed
  by `COUNTDOWN_TIERS` (`"urgent"`, `"soon"`, `"later"`, `"past"` —
  `models.py`), replacing one flat color applied only to the two "urgent"
  tiers. `PremiumStyleUpdate.countdown_colors` takes the same per-key patch/
  merge semantics as `status_colors`; `routers/premium.py`'s `update_style`
  merges it the same way.
- `GET /tmdb/credits` now also returns a department-tagged `crew` list
  (every crew member other than the already-separate director(s)/
  creator(s), tagged with `department`/`job`), and the `cast` and
  `directors` lists are no longer capped (was 12 cast / 4 directors).
- `vote_count` now travels alongside `vote_average` in `/tmdb/search`,
  `/tmdb/trending`, `/tmdb/popular`, and title details.

### Changed

- **Rating scale: 1-10 → 1-100** (`schemas.py`'s `LibraryEntryCreate`/
  `LibraryEntryUpdate`/`EpisodeSet` bounds; `models.py` columns re-documented,
  no type change). Historical ratings migrated by ×10 (migration
  `b5f3a1c9d7e2`). TV Time star-rating imports rescale ×20 instead of ×2
  (`users/tvtime_import.py`). TMDB's `vote_average` rescales ×10 instead of
  rounding to one decimal (`routers/tmdb.py`). Displayed averages
  (`GET /media/ratings`, `/media/ratings/batch`, `_ratings_summary`,
  `GET /stats`'s `avg_rating`) now round to a plain integer instead of one
  decimal place. `GET /stats`'s `rating_distribution` is now bucketed into
  10 deciles (`"1-10"`, `"11-20"`, ..., `"91-100"`) instead of one bucket
  per raw value.
- Premium color fields (`ring_color`, `name_color`, `home_season_color`,
  `home_series_color`, `status_colors`, `countdown_colors`) now accept any
  well-formed `#rrggbb` hex (`schemas._HEX_COLOR_RE`) instead of requiring
  membership in `premium.PALETTE`. `GET /premium/palette` is unchanged —
  it's now a suggested-swatch list rather than an enforced allowlist.
- `routers/upcoming.py`'s `get_upcoming`/`get_upcoming_history`: each row's
  `poster_url` now comes from `entry.poster_url` (honors a premium user's
  custom poster override) instead of `title.poster_url`; all three queries
  now eager-load `WITH_TITLE_GENRES` to avoid a lazy load per row.
- `users/renar_import.py`: imported ratings are now clamped to `1-100` and
  discarded (not silently written) if they're outside that range or not a
  plain int — a corrupted/foreign-version export can no longer write an
  invalid rating via import.

### Fixed

- `routers/media.py`'s `_sync_progress`: the "completed no longer holds up"
  demotion branch now only runs when `total` (aired episode count) is
  truthy — previously a film (which has no episode concept, so `total` is
  always `None`) fell into this branch on every rewatch and was wrongly
  demoted from `completed` back to `want_to_watch`.

## [0.10.0] - 2026-08-03

### Added

- `users/premium.py`'s `THEME_NAMES` expanded: eight new built-in premium
  themes added (`solarized_dark`, `monokai`, `one_dark`, `everforest`,
  `everforest_light`, `catppuccin_latte`, `ayu_dark`, `ayu_light`);
  `gruvbox_soft` removed (the icon asset was dropped from the frontend in
  the same pass). Stored `theme` values that no longer appear in
  `THEME_NAMES` are not retroactively invalidated — only the next `PATCH
  /premium/style` that touches `theme` would fail a validation check.

### Fixed

- `__main__.py`'s uvicorn `run()` call now passes
  `timeout_graceful_shutdown=5`. Without it, a `Ctrl+C` while any `/events`
  (SSE) client was still connected caused uvicorn to log "Waiting for
  connections to close" and hang indefinitely — the SSE stream holds its
  HTTP connection open until the client disconnects, so uvicorn's default
  behavior was to wait for every frontend session to close before the
  process could exit. Five seconds is long enough for in-flight non-SSE
  requests to drain and short enough not to be noticeable in dev use.
  (The companion `_ShutdownCancellationSilencer` in `main.py`, shipped in
  0.9.0, addresses the traceback noise from torn-down connections; this
  addresses the hang that forced a second `Ctrl+C`.)

### Removed

- Three Alembic migrations ship in this release whose net schema effect is
  zero: `a1c9e4f7b3d2` (added `custom_themes` table, `users.custom_theme_id`
  FK, `site_settings.premium_custom_themes_enabled`), `aa0b78014ee0` (added
  `custom_themes.theme_colors`), and `02638e4154de` (drops all of the
  above). The custom-themes backend design was reverted before any release;
  the feature is handled frontend-only instead (see
  `docs/design-decisions.md` "Custom themes are frontend-only, not a backend
  resource"). Operators running `alembic upgrade head` will see all three
  execute in sequence; the resulting schema is identical to the pre-`a1c9e4f7b3d2`
  head.

## [0.9.0] - 2026-07-31

### Added

- `User.email_confirmation_bypassed` (migration `6d15f435ffcf`): marks
  accounts whose `email_confirmed` was set to `True` without a real OTP
  round trip — registered while `SiteSettings.email_confirmation_enabled`
  was off, or bulk-confirmed when an admin disabled that toggle. Purely
  informational (nothing re-gates on it); the admin user list's email
  tooltip now distinguishes "email confirmed" from "email confirmed
  (bypassed: OTP was off at signup or when disabled)".
- `/auth/confirm-email-session`, `/auth/resend-confirmation-session`,
  `/auth/change-unconfirmed-email-session`: bearer-token twins of the
  existing credential-based email-confirmation endpoints, for a
  still-logged-in but unconfirmed session (e.g. a restored session inside
  the grace period) where re-asking for the password would be redundant.
  `UserOut` gained `email_confirmation_bypassed` so the client can see it.
- Site Settings page grew an Email section: sender name/address,
  confirmation-code lifetime, login grace period, and unconfirmed-account
  cleanup age are now admin-editable (`SiteSettings.email_sender_address`/
  `email_sender_name`/`confirmation_code_ttl_minutes`, migration
  `4b2026dc80cd`; `email_confirmation_grace_days`/
  `unconfirmed_account_cleanup_days`, migration `68156a912acf`) instead of
  fixed constants in `users/email_confirmation.py`.

### Changed

- `routers/media.py`'s `_ratings_summary` now also returns the item's own
  `item_status`/`item_episodes_watched`/`item_current_season`/
  `item_current_episode` — fields a rating/watch toggle can silently
  auto-promote or demote (status changing on an episode toggle) — so a
  caller already holding the rating-summary response can update its own
  copy of the item without a follow-up `GET`. (Consumed by
  renar-frontend's `title_view.py`'s new `apply_item_status` helper.)
- `bulk_episodes`'s future-episode guard now runs one query for the whole
  batch (`_assert_no_future_episodes`) instead of one query per episode —
  up to ~24 queries for a full season down to 1.
- Admin user list/detail: premium and verified badges render as their
  actual brand SVG icon (matching the app) instead of a text pill; the
  "grandfathered" pill is gone (see the `email_confirmation_bypassed`
  entry above — the concept it named no longer exists); the email cell is
  now color-coded by confirmation state with a tooltip explaining why;
  granting the verified badge now asks for confirmation before submitting.

### Fixed

- Uvicorn logged a full "Exception in ASGI application" traceback for
  every open connection (notably the `/events` SSE stream) torn down by a
  Ctrl+C/shutdown — `asyncio.CancelledError`/`anyio.WouldBlock` are
  `BaseException` subclasses and skip every `except Exception` in the
  FastAPI/Starlette stack. `main.py`'s new `_ShutdownCancellationSilencer`
  wraps the app (served as `asgi_app`, kept separate from `app` so tests
  keep using the plain `FastAPI` instance) and downgrades it to one clean
  log line.
- `tmdb/tmdb_store.py`'s `warm_title_translations` held one DB session open
  for its entire loop of per-title TMDB HTTP round trips, starving the
  connection pool under load (incident 2026-07-29). Each title now gets
  its own short-lived session, released before the next title's network
  call.

## [0.8.0] - 2026-07-28

### Added

- `Image.source_url` (migration `40c05acfeddb`): the TMDB alternate URL an
  image was downloaded from, recorded by `image_row_for()` on whichever row
  the bytes resolve to, whenever that row doesn't have one yet — including
  a dedup hit against a row created before this column existed, or an
  upload-only row later matched by a TMDB pick with identical bytes
  (uploads themselves leave it `NULL`). The backfill-on-dedup-hit matters in
  practice: this column shipped with no backfill, so re-picking the exact
  alternate a user already had set — the obvious first thing to try — used
  to silently do nothing until this was added. `LibraryEntry` exposes the
  result as `custom_poster_source_url`/`custom_backdrop_source_url`, and
  `set_custom_poster`/`set_custom_backdrop`/`set_custom_episode_still`
  (`routers/media.py`) now pass `data.tmdb_url` through; `list_episodes`'
  `custom_stills[]` gained the equivalent `still_source_url`. Lets
  renar-frontend's alternates picker highlight whichever tile is the
  current pick — comparing the re-hosted `/images/<hash>` URL against TMDB
  CDN URLs could never match otherwise
- `InviteCode.last_used_at` (migration `a73fd0cecbb5`): set on every
  redemption (`routers/auth.py::register`). Used by the admin invites page
  to tell whether a code that's both past its `expires_at` and at its
  `max_uses` hit one boundary before the other, so the status pill (and
  which restore action to offer) reflects what actually happened first
- Admin invites page (`routers/admin/invites.py`): a code can now be both
  time-expired and use-exhausted at once — the row shows both status pills
  side by side instead of only one hiding the other. `POST
  /invites/{id}/reset-uses` resets an exhausted-only code's `uses` to 0;
  `POST /invites/{id}/restore-expiry` gives a time-expired code a new
  `expires_at` (or "Never") and resets `uses` together, via a per-row
  popover with the same 24h/7d/30d/Never/Custom chip presets as invite
  creation
- Admin settings page (`routers/admin/settings.py`): the exempt-IPs field
  is now a tag input (pill per IP + a bare text field in the same box)
  instead of a raw comma-separated text box, submitting the same
  comma-separated value the backend already parses
- `GET /events` (`routers/events.py`): Server-Sent Events stream pushing
  `settings_changed` to every open session of the caller's account,
  backed by an in-process pub/sub (`events.py`, single-worker only — see
  `docs/design-decisions.md`). `PATCH /auth/profile` and `PATCH
  /premium/style` (`routers/auth.py`, `routers/premium.py`) publish the
  event after committing, so a language/theme/style change on one device
  reaches every other open session without waiting on its next navigation
  or app-resume. SSE chosen over a WebSocket since the `websockets`
  package has no prebuilt wheels for renar-frontend's Android/iOS build
  targets — see renar-frontend's CHANGELOG for the client side
- `tests/test_events.py`: pub/sub unit coverage (subscribe/unsubscribe,
  publish delivery, publish to an unknown/empty user, publish dropping
  silently on a full queue) plus the `GET /events` auth gate; the stream's
  own infinite generator isn't opened directly since the sync `TestClient`
  can't hold it open and issue a second concurrent request without
  deadlocking against it

## [0.7.1] - 2026-07-28

### Added

- Export cooldown and expiry: `ExportJob.completed_at` (migration
  `275461ed120c`, backfilled to `queued_at` for existing ready rows), set
  when a build finishes (`export_queue.py::_run`). `POST /export/data`
  now 429s with a "you can request a new one in N days/hours" message
  (`routers/export.py::_format_retry_at`) while a ready export is still
  within its account's expiry window; `GET /export/data/status` and
  `/export/data/download` both fall back to `never_requested`/404 once
  that window passes, via the new shared `users/export.py::export_is_ready`
  (also closes a bug where a DB row could outlive its file and the two
  endpoints would disagree). Window is tier-based
  (`EXPORT_EXPIRY_DAYS_FREE` = 7, `EXPORT_EXPIRY_DAYS_PREMIUM` = 1 —
  same compute-priority-only reasoning as the existing queue-order perk)
- `users/export.py::purge_expired_exports()` deletes the file, `ExportJob`
  row, and `export_queue` in-memory cache entry for every expired ready
  export; run on a schedule by a new `export_cleanup` periodic task
  (`social/notifier.py::_export_cleanup_loop`, `task_runs.py`, admin
  Periodic Tasks page)
- `export_queue.forget()` — drops a user's cached progress entry, used by
  `purge_expired_exports` so a stale in-memory "ready" doesn't keep
  answering ready after the file and row are gone

### Fixed

- Marking future (unaired) episodes as watched was only blocked client-side;
  `PUT /media/{id}/episodes/{season}/{episode}` and
  `POST /media/{id}/episodes/bulk` accepted the same request straight against
  the API. Added `routers/media.py::_assert_not_future_episode()`, called
  before either endpoint writes an `EpisodeWatch` row, raising 422 when the
  episode exists in the `Episode` catalog with a known future `air_date`
  (missing catalog row or `NULL` air date is still allowed, treated as
  possibly aired/untracked). Six new tests in `tests/test_episodes.py`.

## [0.7.0] - 2026-07-27

### Added

- `users/renar_import.py`: restores an account from its own `users/export.py`
  `.7z` export (profile/library/comments/social) — the write side of GDPR
  Art. 20 data portability, so a lost account or a fresh install pointed at
  an empty database gets everything back. Every row already carries its
  own `tmdb_id` so there's no fuzzy TMDB matching; runs synchronously on one
  thread. Merge semantics mirror the TV Time importer: existing rows are
  only filled in or extended, never clobbered, so re-running is safe. Only
  `following` is restored on the social side
- `GET /import/sources`: lists `(kind, label)` for every registered
  importer, feeding the frontend's "which are you importing from?" picker
- `routers/imports.py` generalized from a single hardcoded TV Time importer
  to a registry (`IMPORTERS`) of pluggable origins, dispatched by
  auto-detecting the uploaded file's content rather than trusting the
  filename. `POST /import/tvtime` and `GET /import/tvtime/status` are
  replaced by `POST /import` (takes an optional `claimed_kind`, cross-checked
  against detection and rejected on mismatch) and `GET /import/status`
  (reports on whichever importer last ran for the caller)
- `ImportJob` (models.py) now keyed by `(user_id, kind)` instead of just
  `user_id` (migration `76058e1d65e8`, backfills existing rows to
  `kind='tvtime'`), so an account can hold outcomes from more than one
  import origin without one clobbering the other

### Changed

- `users/export.py`'s GDPR export is now a `.7z` archive with one JSON file
  per category (`profile.json`, `library.json`, `comments.json`,
  `social.json`) instead of a single `data.json` inside a `.zip` — mirrors
  how Google Takeout and similar exports split by category. Comment entries
  now also carry `id`, `parent_id`, `tmdb_id`, and `media_type` so
  `renar_import.py` can restitch reply chains and match titles without
  re-resolving them
- `GET /export/data/download` now names the file
  `renar-export-<built-at>.7z` (timestamp from the export's own build time,
  via `Content-Disposition`) instead of a fixed `renar-export.zip`

## [0.6.0] - 2026-07-26

### Added

- `library_entries.last_watched_at`: timestamp stamped only on genuine
  watch activity — an episode toggled watched/unwatched (`_sync_progress`),
  a rewatch (`POST`/`DELETE .../rewatch`), coarse progress edits
  (`episodes_watched`/`current_season`/`current_episode` via the `PATCH`),
  or a status change into `watching`/`completed`. Deliberately NOT touched
  by favorite, rating, notes, url, or any other `PATCH` field, so
  Home's "continue watching" ordering reflects real viewing history only.
  Migration `b7f3d0a91c4e` adds the column and backfills existing
  `watching`/`completed` rows from each item's latest `episode_watches.watched_at`
  (fallback: `updated_at`) so no in-progress show vanishes on rollout
- Composite index `ix_media_items_user_id_last_watched_at` (migration `b7f3d0a91c4e`)
- `users.password_changed_at`: bumped on every password change — self-service
  (`POST /auth/change_password`) and admin reset (`set_user_password`); migration
  `c1d4e7f2a9b6`. `users/auth.py`'s `get_current_user` rejects any bearer token
  whose `iat_ts` claim predates this value, so a leaked/stolen token stops working
  the instant the password it was minted under is replaced, rather than surviving
  for the rest of its expiry window. `iat_ts` is a custom float JWT claim carrying
  the issuance instant at full microsecond precision — the standard `iat` claim
  is floored to whole seconds by PyJWT, too coarse to distinguish tokens issued
  within the same second of a password change
- `POST /auth/change_password` now returns a `Token` (fresh access token) instead
  of 204 — since changing the password revokes every previously issued token
  (see above), the caller receives a new one automatically so their own session
  stays live without a separate login call
- `routers/media.py`'s `_mark_all_aired_watched`: called when `update_media` sets
  a show's `status` directly to `completed` without an accompanying
  `episodes_watched` count — fills in `EpisodeWatch` rows for every episode whose
  `air_date` is in the past, so per-episode ratings/rewatch have a real history
  to work from instead of zero rows; `_sync_progress` re-counts immediately after
  and won't demote the status (it uses the same aired-only threshold)
- `routers/media.py`'s `_aired_episode_total`: `_sync_progress` now uses the count
  of episodes with `air_date <= today` as the 100% threshold — a still-airing show
  the user has fully caught up on can now auto-promote to `completed` / "Caught up"
  instead of remaining stuck while future episodes are announced. Falls back to
  `Title.total_episodes` when no synced `Episode` rows exist for the title
- `_sync_progress` status demotion on unwatch: unwatching an episode can undo
  the `completed` auto-promotion, rolling back to `watching` (some episodes
  remain) or `want_to_watch` (no episodes remain); previously the status stayed
  `completed` forever once auto-promoted even if the user then unmarked episodes
- `DELETE /media/{item_id}/rewatch`: removes the most recent `WatchEvent` for
  a given item/episode, without touching the `EpisodeWatch` row — inverse of
  `POST .../rewatch`, one event at a time, so the user can step an
  already-rewatched episode down by one rather than jumping straight to
  fully-unwatched
- `list_media` (`GET /media`): new `order_by=last_watched` query parameter;
  orders by `library_entries.last_watched_at desc nullslast`. Default remains
  `updated_at desc`; Library browsing/filtering is unaffected. Used by Home's
  "continue watching" preview
- `create_media` (`POST /media`): stamps `last_watched_at` when an item is
  added directly in `watching` or `completed` status, matching `update_media`'s
  rule that a status transition into those states is itself a watch signal
- TV Time import: trailing-year extraction — TV Time appends a disambiguation
  year to same-named shows (`Shogun 1980`, `Shogun (1980)`); `_split_trailing_year`
  separates base title from year, passes `first_air_date_year` to TMDB, and
  retries without the year (then verbatim) on a miss
- TV Time import: CJK space-stripped retry — TMDB tokenizes on whitespace;
  a stray space in a CJK title that TV Time and TMDB space differently returns
  zero results; `_cjk_space_stripped` strips all spaces for a second query when
  the title contains CJK characters
- TV Time import: fuzzy fallback (`_fuzzy_search` / `_FUZZY_THRESHOLD = 0.8`) —
  drops trailing words from the query, collects a candidate pool across retries,
  picks the best `difflib.SequenceMatcher` match above the threshold; applied
  as the final fallback for both TV and movie matching after all exact/year-split
  retries fail
- TV Time import: one-off special/OVA fallback — items still unmatched after
  movie/show matching are tried as episode references: `_show_episode_splits`
  splits the name on `" - "` / `": "` into candidate show+episode pairs,
  `_search_tv` resolves the show, `_show_episode_pool` fetches every episode
  (season 0 included), and `_match_episode_in_pool` picks the best match above
  `_EPISODE_THRESHOLD = 0.75`; a missing show parent is created so the episode
  has somewhere to attach; `seen` tracks watched episodes across both the main
  loop and this fallback to avoid duplicates
- TV Time import: `_search_movie` falls back to `_search_tv` once the movie-side
  exhausts all retries — handles TV originals mis-catalogued as movies in TV
  Time exports; result is inserted as a `tv_show` entry using `name` /
  `first_air_date` fields rather than movie ones
- TV Time import: `_upsert_library_entry` now returns a fifth `duplicate_in_run`
  flag — the race loser in a concurrent same-run insert collision; callers skip
  the count for those entries so a brand-new account import never misreports a
  title as "already in your library"
- TV Time import: process-wide `_import_slots` semaphore (`MAX_CONCURRENT_IMPORTS
  = 3`) — concurrent imports over the cap get 429 instead of each holding up to
  200 MB simultaneously; slot acquired before reading the upload body, released
  in `_run_import`'s `finally` block
- `__main__.py`'s `_log_config()`: replaces the old `logging.basicConfig` + single
  filter with a full uvicorn-compatible log config — rotating file handler
  (`logs/renar-backend.log`, 10 MB × 5 backups, UTF-8, no ANSI codes), plain
  console handler; TMDB image proxy requests (`/tmdb/image/`) added to the
  console quiet-path filter while the file handler remains filter-free. `logs/`
  added to `.gitignore`
- `tests/test_admin.py`: email normalization test (admin edit must not create a
  case-variant duplicate), username normalization test
- `tests/test_auth.py`: `test_change_password_invalidates_previously_issued_token`,
  `test_activity_touch_throttled_within_interval`,
  `test_activity_touch_fires_again_after_interval`

- `routers/media.py`'s `update_media`: rejects `episodes_watched`,
  `current_season`, `current_episode` with 422 when the target item's
  `media_type` is `film` — those fields are TV-show-only and nothing
  previously stopped a buggy caller from writing them to a film row (the
  frontend hero-card bug did exactly this; see renar-frontend's changelog)

- `resync_tmdb_metadata` / `resync_tmdb_metadata_once` in
  `social/notifier.py`: periodic background job that re-fetches TMDB
  poster/backdrop/details for every tracked title regardless of watch
  status or show state — the only job that revisits completed/dropped/ended
  titles, so TMDB poster changes eventually reach them too
- `_tmdb_metadata_resync_loop` in `social/notifier.py`: fourth independent
  background loop, paused/rescheduled via the same `task_runs.py`
  enable/interval/status mechanism as the existing three; visible on the
  admin Periodic Tasks page
- `task_runs.py`: `TaskSpec` entry for `tmdb_metadata_resync` (label
  "TMDB metadata resync", group "General", default 2880-minute / 48-hour
  interval)
- `tests/test_tmdb_resync.py`: happy-path and error-path coverage for
  `resync_tmdb_metadata` (completed show, dropped film, fetch failure,
  empty library)
- `routers/tmdb.py`: `_poster_overrides` helper — for premium users,
  splices their `LibraryEntry.custom_poster_url` into `/tmdb/search`,
  `/tmdb/trending`, and `/tmdb/popular` results wherever the result set
  contains a title they have in their library
- `routers/tmdb.py`: `w1280` added to `ALLOWED_IMAGE_SIZES` for the
  frontend's tap-to-zoom backdrop dialog
- `alembic/versions/a3f8c1e97b52_remove_book_and_youtube_media_types.py`:
  migration that deletes `book`/`youtube` library entries and title rows,
  recreates the `mediatype` enum without those values, and drops the
  `author`/`page_count` columns from `titles`
- Cloudflare Turnstile captcha on registration: `users/turnstile.py`'s
  `verify_turnstile` calls Cloudflare's siteverify endpoint from
  `POST /auth/register`; `SiteSettings.turnstile_enabled` (migration
  `86c66fe120eb`) lets an admin fall back to IP rate-limiting only without
  touching `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY`. The widget itself is
  hosted backend-side (`new_widget_session`/`widget_html`/`set_widget_token`/
  `get_widget_token` in `users/turnstile.py`, `GET /auth/turnstile-widget/{id}`,
  `POST /auth/turnstile-callback/{id}`, `GET /auth/turnstile-token/{id}`)
  since Cloudflare's widget requires a real, Cloudflare-registered hostname
  and only the backend is reachable from both the web build and compiled
  mobile apps; session state is an in-process dict, so this needs moving to
  shared storage before running multiple uvicorn workers
- `GET /auth/registration-status`: now also returns `turnstile_site_key`
  (null when Turnstile isn't configured/enabled) and
  `email_confirmation_enabled`, both marked `Cache-Control: no-store` so an
  admin toggle takes effect on the very next app launch instead of whenever
  an intermediate cache's stale entry expires
- Registration/email-change confirmation codes: `users/email_confirmation.py`
  generates a 6-digit, bcrypt-hashed code (15-minute TTL, 8-attempt cap) and
  sends it via Brevo (`BREVO_API_KEY`/`EMAIL_SENDER_ADDRESS` in `.env`; unset
  key logs the would-be email instead of sending). New `routers/auth.py`
  endpoints: `POST /auth/confirm-email` (credential-based, not bearer-token,
  so an account past its login grace period can still confirm),
  `POST /auth/resend-confirmation` (throttled: 3 per 5 minutes per account),
  and `POST /auth/change-unconfirmed-email` (fixes a typo'd registration
  address pre-confirmation via a direct rewrite, skipping the two-step
  old-address-approves flow that already-confirmed accounts use). `register`
  sends a `"register"` code when `SiteSettings.email_confirmation_enabled` is
  on; `update_profile`'s email change now goes through a two-step
  `change_authorize`/`change_confirm` code pair instead of changing `email`
  immediately. `login` blocks an unconfirmed, non-grandfathered account once
  `EMAIL_CONFIRMATION_GRACE_DAYS` (7) have passed since `created_at`, with a
  distinct `email_not_confirmed` detail string so the frontend can route to
  a confirm screen instead of a dead end
- `models.py`: `User.email_confirmed` (indexed — filtered on every
  `/stats/ranking` request), `User.email_confirmation_grandfathered` (every
  account that existed before this feature shipped, backfilled by migration
  `ffffe2b24717` so an established user base isn't locked out on day one —
  see that migration's docstring for the exact bug it fixes in `ee151fb9d02c`'s
  original no-grandfathering design), `User.pending_email` (set while a
  two-step email change is awaiting confirmation); `SiteSettings.
  email_confirmation_enabled` (migration `4220e67045f7`); new
  `EmailConfirmationCode` model/table (migration `ee151fb9d02c`) storing
  `code_hash`, `purpose` (`register`/`change_authorize`/`change_confirm`),
  `attempts`, `expires_at`, `consumed_at`
- `db_triggers.py`: `app_counters.total_users` now counts only
  `email_confirmed` users, so a hand-registered throwaway account can't pad
  the `/stats/ranking` denominator or "ahead of me" count past a captcha
  alone — a second trigger (`trg_users_email_confirmed`) watches `UPDATE`s
  that flip the flag in either direction, since the email-change flow can
  flip a confirmed user back to unconfirmed until the new address verifies
- `task_runs.py`: `TaskSpec` entry for `email_confirmation_cleanup`
  (label "Email confirmation cleanup", group "Security", default
  360-minute interval); `social/notifier.py`'s
  `_email_confirmation_cleanup_loop` (fifth independent background loop)
  calls `users/email_confirmation.py`'s `cleanup_unconfirmed_accounts`,
  which deletes `email_confirmed=False`, non-grandfathered accounts older
  than 14 days via `users/accounts.py`'s `delete_account`, so a
  never-confirmed signup doesn't squat a username/email forever
- Personal-data export (GDPR Art. 20): `users/export.py`'s `build_export`
  reads every account, library, comment, and follow/follower row for a user
  directly off the ORM (deliberately not reusing the `*_out` API schemas, so
  the export stays complete and stable as the API surface evolves) into a
  zipped `data.json`. `users/export_queue.py` runs builds on a single
  background worker thread with a priority heap — premium requests dequeue
  ahead of free ones (compute-priority perk only; the export itself stays
  free for every account per GDPR Art. 20) — and mirrors live progress into
  the durable `ExportJob` row (migration `a4d6e1b8c2f7`) so a status poll
  after a server restart can tell "queued job got dropped" apart from
  "never requested". New `routers/export.py`: `POST /export/data` (queues a
  build, 409 if one is already in flight), `GET /export/data/status`,
  `GET /export/data/download`
- Admin **Premium Features** page (`routers/admin/premium.py`,
  `GET <ADMIN_PATH>/premium`): one card per premium perk (profile style,
  verification requests, background image, paid themes, paid progress
  styles, paid episode label styles, leaderboard ranking) grouped into
  Profile & identity / Appearance & personalization / Stats & competition
  sections, each with its own instant on/off switch
  (`POST <ADMIN_PATH>/premium/toggle`) backed by a new
  `SiteSettings.premium_<feature>_enabled` column per feature (migrations
  `b4c6a1e0f923` for style/verification/background/themes/progress_style/
  episode_label, `a1f5e8c3d629` for ranking); tile added to the admin
  dashboard. `users/premium.py`: `PremiumFeature` literal, `PREMIUM_FEATURES`,
  `feature_enabled()` (site-wide toggle lookup), `premium_active()`
  (subscription active AND that perk's toggle on) — `require_premium` in
  `users/auth.py` still only checks the subscription itself; each
  endpoint/field checks its own feature toggle separately since they
  disable one perk at a time rather than premium as a whole. Enforced in
  `routers/auth.py`'s `update_profile` (background image, themes, progress
  style, episode label style), `routers/premium.py`'s `update_style` and
  `request_verification`, and `routers/stats.py`'s ranking endpoints
- Paid episode label styles: `users/premium.py`'s `FREE_EPISODE_LABEL_STYLES`
  (`"cross"` only) / `EPISODE_LABEL_STYLES` (adds `standard`, `literal`,
  `verbose`); `User.episode_label_style` column (migration `c7d8e9f0a1b2`);
  `ProfileUpdate.episode_label_style` with a validator against
  `EPISODE_LABEL_STYLES`
- Premium per-status Library accent colors: `User.status_colors` JSONB column
  (migration `d3e9f6a2b7c1`); `PremiumStyleUpdate.status_colors` accepts a
  per-key patch (`{"status": "#hex" | None}` — `None` clears that one status,
  omitted keys keep their value, top-level `None` clears all), validated
  against `WatchStatus` members and `PALETTE`; `routers/premium.py`'s
  `update_style` merges the patch into the stored dict instead of replacing
  it wholesale
- Admin **Users** page: "Until date" and "Grant forever" premium-grant forms
  alongside the existing "Grant days" one (`routers/admin/users.py`'s
  `grant_premium` now accepts `days` OR `until_date` OR `forever`, dropping
  the old 3650-day cap on `days`); `PREMIUM_FOREVER` sentinel
  (`datetime(9999, 1, 1, tzinfo=UTC)`, since `is_premium` only ever checks
  `premium_until > utcnow()` and `datetime.max` doesn't round-trip through
  every DB driver); "email confirmed" / "grandfathered" pills next to a
  user's existing premium/verified pills
- TV Time import now also carries over comments and rewatch counts:
  `routers/imports.py` reads `show_comment.csv`/`episode_comment.csv`/
  `comments-prod-comments.csv` (filtered to `type` `comment`/`reply` rows)
  into `Comment` rows, reconstructing reply threads via each row's TV Time
  `id`/`parent_comment_id` (or `uuid`/`parent_uuid` for movie comments)
  through a retry-until-no-progress loop so a self-reply chain resolves
  regardless of row order — a reply whose parent is never one of this user's
  own comments (the common case: a reply to another TV Time user) is
  dropped rather than filed as a fake root comment. `rewatched_episode.csv`
  tops up each episode's `WatchEvent` row count to TV Time's own `cpt`
  count without ever double-counting a rewatch already logged manually or
  via `POST /rewatch`, and creates the `EpisodeWatch` row if missing.
  `_match_show` now falls back to a plain TMDB title search
  (`_search_tv(name)`) when both the TVDB-id lookup and the TVDB-alias
  retry come up empty (or no `TVDB_API_KEY` is set), instead of leaving the
  show unmatched
- `catalog/titles.py`'s `backfill_title_tmdb_id`: fills in `tmdb_id` (and
  any still-missing poster/runtime/episode-count metadata) on a `Title` that
  was created without a TMDB match on an earlier import run, called from
  `routers/imports.py`'s `_upsert_library_entry` whenever a later run
  resolves a `tmdb_id` for a title-text match that previously had none —
  without this, a text-matched reconcile updated the `LibraryEntry` but
  left the underlying `Title` permanently degraded. Race-safe: a concurrent
  worker claiming the same `tmdb_id` for a different `Title` (a genuine
  `uq_title_tmdb` collision) is caught and skipped rather than raised
- `import_jobs` table (migration `b2f7a6d391ea`) and new `ImportJob` model:
  durable marker for a user's last TV Time import outcome, written at job
  start and completion/failure only, so `GET /import/tvtime/status` can
  tell "server restarted mid-import" apart from "never run" after the
  in-memory `_progress` dict is lost; `routers/imports.py`'s `_run_import`
  now also tracks per-row `errors` (infra failures) separately from
  `skipped` (normal dedupe) in the returned summary
- `GET /upcoming` and `GET /upcoming/history` (`routers/upcoming.py`) both
  gained a `media_type` query filter and now return `tmdb_id` per entry

### Changed

- `routers/tmdb.py` `image_proxy`: no longer injects `db` via
  `Depends(get_db)` — each of the two short DB touches now opens its own
  `SessionLocal()` so a pooled connection is not held across the outbound
  TMDB fetch; grid loads of unseen posters are no longer bottlenecked by
  the DB pool size
- `routers/tmdb.py` `alternate_episode_stills`: episode still URLs changed
  from `w780` to `original` for full-resolution stills
- `routers/tmdb.py` `season_tmdb`: per-episode still URLs changed from
  `w342` to `w300`
- `tmdb/tmdb_http.py`: in-memory TMDB cache TTL raised from 30 minutes to
  6 hours (`CACHE_TTL_SECONDS`); trending/popular/search results don't
  meaningfully change within a day on TMDB's side
- `social/notifier.py` `check_new_episodes` / `check_upcoming_films`:
  changed from one batch commit per full scan to one `db.commit()` per
  title, to avoid holding `tmdb_cache` row locks across the entire loop and
  deadlocking against concurrent background loops updating the same rows in
  a different order
- `media/http_cache.py` module docstring: removed references to Open
  Library and YouTube Data API (no longer used)
- `UserCreate`/`register`: emails are now normalized (`.strip().lower()`)
  before the uniqueness check and storage, in `routers/auth.py`'s `register`
  and `update_profile`, so `Foo@Example.com` and `foo@example.com` can't
  both register or collide inconsistently
- `routers/admin/settings.py`: Site Settings page gained Turnstile captcha
  and Email confirmation status chips/toggles, plus warning banners when
  `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` or `BREVO_API_KEY` aren't set
  in `.env`; turning email confirmation off bulk-confirms every currently
  unconfirmed account (one row-level `UPDATE`, so `app_counters.total_users`
  comes out correct via the existing trigger without a separate resync)
  instead of leaving them silently excluded from login/ranking forever
- `routers/upcoming.py`'s `get_upcoming_history`: TV and film history are now
  queried independently (each skipped entirely when `media_type` filters the
  other out) instead of always running both; the history cutoff moved from
  `today + 1 day` to `today`, so a title releasing/airing today shows only
  once, under `/upcoming`, instead of also appearing in `/upcoming/history`
- `__main__.py`: `uvicorn.access` logs for high-frequency polling endpoints
  (`/import/*/status`, `/auth/me`) are now filtered out via a
  `logging.Filter`, so they don't drown out real request traffic in server
  logs (console only; file handler below is now filter-free)
- `pyproject.toml`: added `fastapi.Form` to ruff's
  `flake8-bugbear.extend-immutable-calls` (the admin premium-toggle and
  settings forms use `Form(...)` defaults the same intended way as the
  existing `Depends`/`Query` entries)
- `users/auth.py`'s `_touch_activity`: throttled to at most one DB write per
  `_ACTIVITY_TOUCH_INTERVAL` (15 minutes) per user — all current readers of
  `last_active_at` (admin analytics `active_today`/`active_7d`, admin
  user-detail page, GDPR export) only need day-level accuracy; the previous
  per-request commit was the highest-frequency write on the app's busiest
  dependency
- `routers/admin/users.py`'s `edit_user`: email and username are now
  normalized (`.strip().lower()` / `.strip()`) before the uniqueness check,
  mirroring self-service `register`/`update_profile` — previously an admin
  edit could create a case-variant email duplicate that the unique index
  (case-sensitive) wouldn't catch
- `routers/admin/users.py`'s `set_user_password`: stamps
  `user.password_changed_at = utcnow()`, invalidating any tokens the
  target user currently holds — same effect as the self-service path
- `routers/admin/_html.py`: account-action cards are now laid out in a
  two-column `.actions-grid` (responsive: collapses to one column on
  narrow viewport widths)
- `routers/social.py`'s `list_following` / `list_followers`: apply
  `_DEFAULT_LIST_LIMIT = 60` when `limit` is omitted; previously returned
  an unbounded response regardless of how large the follower/following list was
- `users/export_queue.py`'s `_run`: export failure no longer exposes the
  raw exception string via `ExportJob.error` or `GET /export/data/status`
  — a generic user-facing message is stored instead; the real exception
  still reaches the server log. Same treatment applied to import failures
  in `routers/imports.py`'s `_run_import`
- `database.py`: `create_engine` now passes `connect_args={"connect_timeout": 5}`
  — caps new connection attempts at 5 seconds so a request fails fast with
  a clear error when the DB host is unreachable, instead of hanging until
  the OS TCP timeout fires

### Removed

- `routers/books.py` and `routers/youtube.py` — books and YouTube media
  type support dropped; endpoints, models, and imports removed
- `tests/test_books.py` and `tests/test_youtube.py`
- `models.py`: `MediaType.youtube` / `MediaType.book` enum values; `Title`
  columns `author` / `page_count`; `LibraryEntry` properties `author` /
  `page_count`
- `schemas.py`: `author` / `page_count` fields from `TitleOut`,
  `LibraryEntryCreate`, `LibraryEntryOut`
- `catalog/titles.py` `find_or_create_title`: `author` / `page_count`
  parameters
- `config.py` / `.env.example`: `YOUTUBE_API_KEY` / `youtube_api_key`
  setting (YouTube Data API v3 key no longer needed)
- `routers/stats.py`: `youtube_watched`, `books_read`, `pages_read`
  stat counters from `GET /stats` response

### Fixed

- TV Time import: shows resolved via the concurrent-insert-race path
  (same-run `duplicate_in_run`) were previously counted as "already in your
  library" even on a brand-new account — `duplicate_in_run` now correctly
  skips them in every counting branch so they neither inflate "already in
  library" nor double-count a title that one sibling worker already claimed

- `users/accounts.py`'s `delete_account`: `EpisodeCustomStill` rows have no
  ORM relationship on `LibraryEntry` and no DB-level `ON DELETE CASCADE`, so
  deleting a user whose library entries had custom episode stills previously
  left those rows (and their still images) orphaned instead of being cleaned
  up; now explicitly deleted (with their images GC'd) before the cascading
  user delete. Also now clears `EmailConfirmationCode`, `ExportJob`,
  `ImportJob` rows and the on-disk export zip for the deleted user, and
  nulls (rather than leaves dangling) `InviteCode.created_by_user_id` for
  codes the user created, since those codes may still be valid and in use
  by others

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
