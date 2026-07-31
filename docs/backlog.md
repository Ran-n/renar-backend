[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/07/31 19:02:53.096097 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Known gaps and follow-ups, not yet scheduled.

## Multi-session sync

- **Done — `GET /events` (SSE) pushes account-settings changes to every
  open session.** `routers/events.py` + `events.py`; `PATCH /auth/profile`
  and `PATCH /premium/style` publish `settings_changed` after committing.
  See `docs/design-decisions.md`'s "`GET /events`" entry for the design
  (why SSE not a WebSocket, why in-memory single-worker) and
  renar-frontend's `docs/backlog.md` "Multi-session sync" entry for the
  full story and client side.

- **Not covered: general data sync (watch status, library, comments,
  notifications).** The `/events` push above is account-settings only.
  Marking an episode watched, adding to the library, posting a comment, or
  a new notification on one session still isn't reflected on another open
  session until it re-fetches on its own (view re-entry, poll, etc.) — no
  push for any of that yet. Extending the same `/events` channel with more
  event types (e.g. `library_changed`) is the likely shape of a fix, but
  scope/priority not decided.

## Performance / responsiveness

- **Reduce endpoint latency so the frontend feels snappier — done.**
  Audited the hot endpoints (library listing, explore, title/episode
  detail, profile/social, comments) for N+1 queries, missing eager loads,
  and missing indexes. Fixed:
  - **Comments N+1 (the big one).** `routers/comments.py`'s `_comment_out`
    walked `Comment.author`/`.likes`/`.reports`/`.replies` — all lazy
    relationships — recursively per node; rendering 100 root comments with
    replies fired on the order of hundreds to thousands of queries. Added
    `social/comment_threads.load_thread()`: one recursive CTE to collect
    every comment in a thread (roots + all nested replies), then three
    `selectinload`s for author/likes/reports — fixed query count regardless
    of thread size/depth. `_comment_out` now takes a
    `children_by_parent` dict built from that batch instead of touching
    `Comment.replies`.
  - **`routers/social.py`'s `activity_feed`** wasn't eager-loading
    `title_ref`/genres/custom poster-backdrop images, so `item.poster_url`
    etc. lazy-loaded per row (up to 50/request). Added `WITH_TITLE_GENRES`
    to its query, same as `list_media`/`get_stats`/`user_media` already had.
  - **Missing composite indexes on `Notification`.** Replaced the
    low-cardinality standalone `read` index with
    `(user_id, read)` (backs `list_notifications`'/`unread_count`'s filter)
    and `(user_id, created_at)` (backs the default listing order) — same
    pattern as `LibraryEntry`'s existing composite indexes. Migration
    `45a9dba29ff9`.
  - `list_media`, `get_stats`, `user_media` were already using
    `WITH_TITLE_GENRES` + `prefetch_episode_cache`, so no N+1 there.
  - TMDB-derived metadata caching already exists (`tmdb_http.py`'s
    in-memory cache + `tmdb_store.py`'s DB-persisted `TmdbCache`) — this
    part of the original ask was already done, not new work.

  **`list_media` had no default limit** — an omitted `limit`/`offset`
  returned the caller's entire library unbounded. Fixed: `list_media` now
  defaults to `_DEFAULT_LIST_LIMIT = 60` (matches the frontend's existing
  `library_view.py` page size) when the caller doesn't pass `limit`. That
  required auditing every frontend caller that relied on the old unbounded
  default first (see `renar-frontend`'s now-closed mirror entry) — two of
  the four call sites were actually using `list_media` to build a
  full-library lookup, not a paginated listing, and would have silently
  broken (false "not in library" / false "not found") the moment a large
  library got capped:
  - `routers/media.py`'s new **`GET /media/keys`** — a lean, unbounded
    `(media_type, tmdb_id, title, author, url)` projection (no
    `WITH_TITLE_GENRES` joins, no full `LibraryEntryOut` shape) for
    Explore's "already in my library" icon overlay, which genuinely needs
    every entry, not a page.
  - `routers/media.py`'s new **`GET /media/by_tmdb`** — single-item lookup
    by `(media_type, tmdb_id)` for the title detail page, replacing a
    linear scan over the caller's (previously unbounded) full library.
  - The Home "continue watching" row's `list_media(status_filter=
    "watching")` call now passes an explicit `limit=6` — the most it ever
    renders — instead of relying on the backend handing back everything.

  `get_stats` intentionally still has no `limit`/`offset` at all: it
  aggregates totals (watch minutes, genre counts, streaks, ratings) across
  the *entire* library to produce a single correct number, so pagination
  doesn't apply to it the way it does to a listing endpoint — this wasn't a
  gap, just an imprecise description in the original audit note.

## Flagged during 2026-07-21 full sweep — fixed

- **`users/auth.py`'s `get_current_user` wrote to the DB (`_touch_activity`,
  commit) on every authenticated request — fixed.** Every current reader of
  `last_active_at` (admin analytics' `active_today`/`active_7d`, the admin
  user-detail page, the GDPR export) only needs day-level accuracy, so
  `_touch_activity` now skips the write when the existing value is already
  younger than `_ACTIVITY_TOUCH_INTERVAL` (15 minutes) — cuts the write
  volume by ~two orders of magnitude for an active user without changing
  anything any reader sees.

- **`tmdb/tmdb_http.py` sends the TMDB v3 API key as a URL query
  parameter — investigated 2026-07-21, already correct, no code change.**
  Checked against TMDB's own auth docs
  (https://developer.themoviedb.org/reference/authentication): the
  `Authorization: Bearer` header only accepts a Read Access Token (the
  separate JWT-shaped credential), never the legacy v3 API key — TMDB
  states outright that a v3 key "only works when passed as a query
  parameter, rather than in an Authorization header." `tmdb_get` already
  branches correctly (JWT-shaped key → `Bearer` header, legacy key →
  `api_key` query param), so the query-param path for v3 keys is required
  by TMDB, not a latent bug. The logging-leak risk this entry raised is
  real in the abstract but only for a URL-logging client/middleware that
  doesn't already exist in this codebase.

## Import system (`routers/imports.py`)

Generalized from a single hardcoded TV Time importer to a registry of
pluggable importers (`users/tvtime_import.py`, `users/renar_import.py`, ...)
dispatched by auto-detecting the uploaded file's content — see
`routers/imports.py`'s module docstring for the registry shape. Old
endpoints `POST /import/tvtime` and `GET /import/tvtime/status` are now
`POST /import` (with an optional `claimed_kind` cross-checked against
detection) and `GET /import/status`; `GET /import/sources` is new, listing
every registered origin for the frontend's source picker
([import_view.py](../../renar-frontend/src/renar_frontend/views/profile/import_view.py)).
`ImportJob` (models.py) is now keyed by `(user_id, kind)` instead of just
`user_id` (migration `76058e1d65e8`), so an account's TV Time and Renar
import outcomes don't clobber each other.

- **Renar-native import — added.** `users/renar_import.py` is the write
  side of GDPR Art. 20 data portability: restores an account from its own
  `users/export.py` `.7z` export (profile/library/comments/social), so a
  lost account or a fresh install can get everything back rather than just
  a document to look at. Every row already carries its own `tmdb_id`, so
  there's no fuzzy TMDB matching — it runs synchronously on one thread
  rather than fanning out across a worker pool like the TV Time importer.
  Merge semantics mirror the TV Time importer: an existing row is only
  filled in or extended, never clobbered, so re-running (or importing into
  an account that already has data) is safe. Only `following` is restored
  on the social side — `followers` isn't this account's to recreate. A
  reply's parent is only reconstructed when it's also one of this user's
  own exported comments (same self-reply-only limitation as the TV Time
  importer, documented below).

### TV Time import

- **Infra failures counted as "skipped" — fixed.** `_upsert_library_entry`
  now returns a fourth `error` flag, set only when its `except Exception`
  fires (a real infra failure), never for an ordinary dedupe skip. Callers
  tally it into a separate `summary["errors"]` counter instead of folding it
  into `skipped`, and [import_view.py](../../renar-frontend/src/renar_frontend/views/profile/import_view.py)
  surfaces it as a red "{n} failed due to a server error" line.

- **Transient TMDB failures permanently degrade an entry — reconcile now
  backfills.** If a TMDB lookup fails (rate limit, outage) the row imports
  unmatched (no `tmdb_id`, poster, or episode counts). `catalog/titles.py`'s
  new `backfill_title_tmdb_id` is now called from both reconcile paths in
  `_upsert_library_entry`: when a later re-import resolves a `tmdb_id` for a
  row that reconciles into an existing (tmdb_id-less) entry — whether via
  `existing_map` or the concurrent-insert race's IntegrityError path — the
  shared `Title` is upgraded in place (tmdb_id, title_key cleared, and any
  still-empty poster/runtime/episode-count fields), race-safe against a
  genuine crosswalk collision via `uq_title_tmdb`. Still open: if the
  re-import's title text differs from what's stored, a duplicate entry is
  still created instead of reconciling (identity is still title-key based
  when there's no `tmdb_id` match). No retry/backoff on 429s either, and 8
  concurrent workers make bursts more likely.

- **Server restart mid-import fails silently — fixed.** Progress still lives
  in the in-memory `_progress` dict (fine for normal polling), but a new
  durable `ImportJob` row (models.py, migration `b2f7a6d391ea`) is now
  written at job start and at completion/failure. `GET /import/status`
  (was `/import/tvtime/status`) falls back to it whenever `_progress` has nothing for the user (a new
  process after a restart): `finished=False` there means the job never
  reported back, so the endpoint now returns an explicit "Import was
  interrupted by a server restart" error instead of a fabricated "Never run"
  success.

- **Comments — added.** `show_comment.csv`/`episode_comment.csv` were
  previously ignored entirely, even though they're genuine user content
  (unlike e.g. `user_statistics.csv`, which Renar recomputes itself). Both
  are now read and inserted as root `Comment` rows, scoped only to shows
  matched during the same run (`items_by_tvdb`) — a comment on an untracked
  show is skipped rather than triggering its own TMDB match/library add.
  `episode_comment.csv` has no `tv_show_id` column, only `tv_show_name`, so
  it's matched via a name -> tvdb_id map built from `user_tv_show_data.csv`'s
  own rows; a name collision there would misfile a comment onto the wrong
  show, though TV Time show names are effectively unique in practice.
  `Comment` has no external TV Time id, so re-runs dedupe by
  `(title_id, season, episode, text)` for root comments and by
  `(parent_id, text)` for replies instead. **Reply threads
  (`parent_comment_id`):** reconstructed when the parent is *also* one of
  this user's own exported comments — `tvtime_id_to_comment_id` maps every
  resolved comment's original TV Time id to its new `Comment.id`, retried in
  passes so multi-level self-reply chains resolve regardless of row order,
  and replies onto a comment from a previous import run still resolve since
  a dedupe hit populates the map too. A reply whose parent never resolves —
  the common case, replying to another TV Time user, who by definition isn't
  in this user's own export — is dropped rather than filed as a fake root
  comment, since that would misrepresent what it actually is. Still not
  imported: per-episode emotion/star votes
  (`emotions-v2-prod-votes.csv`, `ratings-v2-prod-votes.csv` — Renar only
  gets the whole-show rating from `tv_show_rate.csv`), custom poster/fanart
  picks (`user_custom_show_image.csv`), and user-made lists
  (`lists-prod-lists.csv`) — none of these have an equivalent Renar model
  yet.

- **Rewatches — added.** `rewatched_episode.csv` was previously ignored.
  Renar *does* have a rewatch concept — `WatchEvent` (models.py) is a
  separate, append-only log next to `EpisodeWatch`'s "currently watched"
  row; `POST /media/{item_id}/rewatch` and `routers/media.py`'s
  `rewatch_count` fields already read/write it (an earlier pass at this
  backlog entry wrongly said Renar had no rewatch concept — it does, this
  was just never wired into the importer). TV Time's `cpt` column is that
  show's own rewatch count per episode; import means topping each episode's
  `WatchEvent` row count up to `cpt`, not overwriting it, so a rewatch
  logged manually (or via the app's own endpoint) survives a re-import, and
  re-running only ever inserts the shortfall. Matched via the same
  name -> tvdb_id map as `episode_comment.csv` (no `tv_show_id` column here
  either). A rewaked-but-never-marked-watched episode gets its
  `EpisodeWatch` row created too, matching what the app's own rewatch
  endpoint already does. TV Time gives one timestamp per row, not one per
  rewatch, so every synthesized event for a `cpt` > 1 row shares it.

- **Import coverage panel — added.** [import_view.py](../../renar-frontend/src/renar_frontend/views/profile/import_view.py)
  now has a "What gets imported?" button opening a dialog that lists every
  category that is and isn't imported, with a one-line reason for each
  omission (no equivalent Renar feature yet, deliberately excluded as
  account/session data, or can't be reconstructed from a single user's
  export). Static content, not server-fetched — it describes the importer's
  fixed behavior, so it only needs updating here in lockstep with
  `routers/imports.py` itself.

- **Minor: concurrent reconciles of the same entry are last-write-wins.**
  Two rows racing to reconcile into the same `LibraryEntry` aren't
  serialized — harmless today since both reconcile functions are monotonic
  (favorite only flips true, rating only fills when empty), but worth a note
  if reconcile logic grows less monotonic later.

- **Minor: `_progress` entries are never pruned.** Negligible memory; clears
  on process restart. Not worth fixing unless it becomes visible.

- **Planned: "watched on" (streaming source) and custom lists.** Two of the
  "no matching feature yet" items are now actually queued, not permanent
  gaps — see the "Custom lists" and "Watched-on / streaming source
  tracking" entries under Features below. Once those Renar-side features
  exist, this importer needs matching read-and-map logic:
  `watched_on_episode.csv`/`followed_tv_show_source.csv` (source id per
  episode/show watch — both files are confirmed present in a real GDPR
  export carrying `watched_on_source_id`; the field exists, only the enum
  isn't documented anywhere in the export itself, so its meaning needs
  reverse-engineering, e.g. by cross-checking a few known-source watches in
  a real account against the app's UI) for watched-on, and
  `lists-prod-lists.csv` for custom lists. Explicitly decided *not* to build
  in this pass: per-episode emotion reactions (`episode_emotion.csv`,
  `tv_show_user_emotion_count.csv`) — real discrete `emotion_id` values do
  exist in the export (unlike star votes, which don't carry a value at
  all — see above), but adding a whole reaction system duplicates the
  existing 1-10 rating for questionable value, and TV Time's emotion enum
  isn't fully documented from the sample export (only 4 of what's
  presumably ~8 values were observed, no confirmed label mapping).

## Features

- **Custom lists.** User-made collections of shows/movies (TV Time has these
  as user-made lists — `lists-prod-lists.csv` in a GDPR export). No
  equivalent model exists yet: needs a `List`/`ListItem` table (or similar),
  ownership, ordering, CRUD endpoints, and UI (create/rename/delete a list,
  add/remove/reorder items, a way to browse a list). Not scoped in detail
  yet — open questions: one list per item allowed or many; public/shareable
  or private-only; does the TV Time importer target this once it exists (see
  the TV Time import section above).

- **Watched-on / streaming source tracking — user priority (2026-07-21).**
  Record which platform/service an episode or movie was watched on (TV Time
  has `watched_on_source_id` per episode watch, and a per-show
  followed-source too). No field for this exists on
  `EpisodeWatch`/`WatchEvent`/`LibraryEntry` yet. Not scoped in detail yet —
  open questions: free-text vs. a fixed enum/picker of streaming services,
  per-watch or per-show granularity, and whether it's shown/filterable in
  the UI or just recorded. The TV Time importer would need
  `watched_on_source_id`'s meaning reverse-engineered first (see the TV Time
  import section above) before it can map source ids to whatever this ends
  up being.

- **Ranking only covers total overall watch time; no badges/achievements
  exist yet.** `routers/stats.py:205-210`'s `RANKING_METRICS` currently
  registers a single metric, `watch_time` (total minutes across
  everything). The ranking system is pluggable by design (add a
  `RankingMetric` entry and it's picked up by `/stats/ranking` and
  `/stats/ranking/metrics` automatically), so this is a scoping/build-out
  gap, not an architecture gap. Wanted: more granular time-based rankings
  (time watching shows vs. movies, time per show, per franchise, per
  genre/category), likely computed from the same watch-history data
  `routers/stats.py` already aggregates. Separately, a TV Time-style
  **badge/achievement system — user priority (2026-07-21)** — unlockable badges for specific
  accomplishments (e.g. finishing a franchise, a binge streak, watching
  N hours of a genre) — doesn't exist at all yet: no `Achievement`
  table, no per-user unlock rows, no UI for it. This is a real departure
  from the current badge design, which is explicitly "one derived badge,
  never a stored list" (see `docs/design-decisions.md`). Needs scoping:
  which per-category rankings to add first, and what the badge set /
  unlock conditions look like.

- **Real email confirmation on registration — done.** `users/email_confirmation.py`
  (codes, bcrypt hashing, Brevo send with a logged-not-sent fallback while
  `BREVO_API_KEY` is unset, resend throttle, cleanup loop) plus
  `routers/auth.py`'s `/auth/confirm-email` + `/auth/resend-confirmation`
  (credential-based — an account past the login grace period has no token to
  authenticate with otherwise) and their bearer-token twins
  `/auth/confirm-email-session` + `/auth/resend-confirmation-session` (for a
  still-logged-in but unconfirmed session, e.g. a restored session inside
  the grace period, where re-asking for the password would be redundant),
  `/auth/change-unconfirmed-email(-session)` (fix a typo'd address before
  the first confirmation — direct rewrite, no old-address approval needed
  since there's no current owner to protect yet), the two-step email-change
  flow in `update_profile`, and a login grace period before an unconfirmed
  account is blocked. `User.email_confirmed` defaults to `False` for every
  row including existing users. This was built specifically to close the
  ranking-inflation gap noted under the Turnstile item below:
  `_compute_ranking` (`routers/stats.py`) and `app_counters.total_users`
  (`db_triggers.py`) now only count confirmed users.

  **Pre-existing accounts:** the original `email_confirmation_grandfathered`
  flag (migration `ffffe2b24717`) exempted every account that existed before
  rollout from the login-gate block and cleanup deletion without marking it
  `email_confirmed`. A later migration replaced that with a simpler,
  permanent fix: every account that existed at rollout time was bulk-marked
  `email_confirmed = True` directly, and the `email_confirmation_grandfathered`
  column was dropped.

  **`email_confirmed` vs. `email_confirmation_bypassed`:** the same "mark it
  confirmed outright, don't track a separate exemption" approach now also
  covers new accounts that register while confirmation is off, and any
  account an admin's kill-switch toggle bulk-confirms — see below. Both
  cases additionally set `User.email_confirmation_bypassed = True`
  (migration `6d15f435ffcf`), a purely informational marker: nothing
  re-gates on it, but the admin user list's email tooltip distinguishes a
  real OTP round trip ("email confirmed") from one that never happened
  ("email confirmed (bypassed: ...)"), and the profile screen offers a
  bypassed account a **voluntary** "Verify email" tile — reusing the
  `-session` endpoints above, with the `email_confirmed` guard on them
  loosened to let a bypassed account through — that clears the flag once
  they complete a real code round trip. Only accounts created *after*
  rollout, with the feature on and never bulk-confirmed, are ever subject
  to the grace-period block/cleanup.

  **Admin kill switch:** `SiteSettings.email_confirmation_enabled` (Site
  Settings page, same pattern as `turnstile_enabled`) — off skips the code
  step for new registrations entirely (bypassed) and immediately
  bulk-confirms every currently-unconfirmed account (bypassed too, so
  nobody stays silently excluded from ranking or blocked at login once the
  feature is off); re-enabling it does not retroactively re-lock anyone.
  The Site Settings page also has a full Email section now: sender
  name/address, confirmation-code TTL, grace-period days, and cleanup-days
  are all admin-configurable (previously fixed constants), plus a warning
  when `BREVO_API_KEY` is unset, since that's the reason codes aren't
  actually being emailed yet. Not yet done: real sending is still off
  (`BREVO_API_KEY` unset by default) pending the subdomain/DNS work in the
  Infrastructure section; the Brevo bounce/complaint webhook.

- **Design the registration flow around the email-confirmation toggle
  flipping on/off — user priority (2026-07-29).** The toggle
  (`SiteSettings.email_confirmation_enabled`) and its two bulk-confirm/
  bypass mechanics above were each added reactively, one migration at a
  time (`ffffe2b24717` grandfathering → `1b63409d9417` dropping it for a
  direct bulk `email_confirmed = True` → `6d15f435ffcf` adding
  `email_confirmation_bypassed`), rather than designed as one flow up
  front. Worth a proper pass rather than another one-off patch.

  **What shipped in the 2026-07-29 session** (context for the open
  questions below — all already covered in more detail in the "Real email
  confirmation" entry above and `docs/design-decisions.md`'s
  "`email_confirmed` is authoritative" entry):
  - Backend: migration `4b2026dc80cd` (email sender name/address and
    confirmation-code TTL moved from fixed constants onto `SiteSettings`)
    and migration `68156a912acf` (grace-period days and cleanup-days,
    same move), both admin-editable on the Site Settings page; migration
    `1b63409d9417` (dropped `email_confirmation_grandfathered`,
    bulk-marked every pre-rollout account `email_confirmed = True`
    directly); migration `6d15f435ffcf` (added
    `User.email_confirmation_bypassed`, set at registration when the
    toggle is off and at the admin's bulk-confirm-on-disable). New
    `/auth/confirm-email-session`, `/auth/resend-confirmation-session`,
    `/auth/change-unconfirmed-email-session` (bearer-token twins of the
    existing credential-based endpoints, for a still-logged-in but
    unconfirmed session); `_resend_confirmation`/`_confirm_email_code`'s
    "already confirmed" guard loosened to let a *bypassed* account through
    (and clear the flag on a real completed round trip), so the voluntary
    flow below has something to call. `routers/admin/users.py`: the email
    cell's tooltip now distinguishes a real OTP round trip from a bypassed
    one; `routers/admin/settings.py` grew the new Email section.
  - Frontend: `confirm_email_view.py` reworked to support session mode
    (`use_session`), client-side code-expiry countdown, reactive
    stale/expired-code detection, and four distinct framings via
    `confirm_reason` (`register`, `login_reminder`, `login_blocked`,
    and the new `voluntary`). New `profile_view.py` "Verify email" tile,
    shown only when `/auth/me` reports `email_confirmation_bypassed`,
    routing into the same view in voluntary/session mode. `UserOut` gained
    `email_confirmation_bypassed` so the client can see it at all.
  - Tests: `tests/test_email_confirmation.py` grew coverage for the bypass
    flag being set on both paths (registration-time, bulk-confirm-on-disable),
    re-enabling not retroactively re-locking anyone, a real OTP round trip
    leaving the flag `False`, and the new voluntary-confirmation-via-session
    path (`test_bypassed_account_can_request_and_complete_voluntary_confirmation`,
    `test_genuinely_confirmed_account_still_rejects_resend`). Full backend
    suite (552 tests) green.
  - Docs: this backlog entry and the "Real email confirmation" entry above
    it, plus a matching pair of entries in renar-frontend's `docs/backlog.md`
    and both repos' `docs/design-decisions.md` — see those for the
    reasoning behind each piece, not repeated here.

  Open questions for the actual design pass:
  - **Toggle-flip races.** `register()` reads
    `ss.email_confirmation_enabled` once to decide `email_confirmed`/
    `email_confirmation_bypassed` at insert time; the admin's bulk-confirm
    on disable is a separate, later `UPDATE ... WHERE email_confirmed IS
    false`. A registration committing between those two isn't provably
    impossible — worth confirming there's no window where a row is
    inserted unconfirmed (feature still reads as "on" to `register()`)
    just as the bulk-confirm's `WHERE` clause is evaluated, and it's
    skipped by one commit's worth of timing.
  - **Re-enabling never re-locks anyone, on purpose
    (`test_reenabling_feature_does_not_unconfirm_bulk_confirmed_users`)**
    — is that the right permanent policy, or should there be a way to
    later require bypassed accounts to actually verify (e.g. if the site
    moves from invite-only/low-trust to open registration and wants to
    tighten retroactively)? Right now the only way back to "really
    confirmed" is the voluntary profile tile, which nothing nudges anyone
    toward.
  - **Ranking currently doesn't distinguish real vs. bypassed
    confirmation** — `_compute_ranking` only checks `email_confirmed`,
    so a bypassed account (never proved ownership) ranks exactly like a
    verified one. Intentional per `docs/design-decisions.md`'s
    "`email_confirmed` is authoritative" entry, but worth an explicit
    product decision on whether that's acceptable long-term, especially
    if the toggle gets flipped off temporarily just to onboard a batch of
    users quickly.
  - **No visibility into how many accounts are bypassed vs. really
    confirmed**, other than reading each row's tooltip one at a time in
    the admin user list — no aggregate count/filter, unlike `total_users`
    or the ranking-eligible count.
  - **The voluntary "Verify email" tile (renar-frontend's
    `profile_view.py`) is entirely passive** — shown, never surfaced via
    notification/reminder/badge. Decide whether that's sufficient or
    whether bypassed accounts should get any kind of nudge, and if so
    how that squares with "no obligation" being the whole point of the
    tile.

- **Soft delete with a 30-day grace period for account deletion.**
  `DELETE /auth/me` (`routers/auth.py:520-525`) currently calls
  `users/accounts.py`'s `delete_account` directly, which purges the user row
  and every referencing row (comments, likes, follows, notifications, login
  events, media items, exports on disk, etc.) synchronously and irreversibly
  in the same request — no recovery window. Wanted instead: mark the account
  for deletion rather than purging immediately; if the user logs back in
  before 30 days elapse, cancel the pending deletion and restore normal
  access; after 30 days with no login, a background job runs the existing
  purge. `delete_account` itself is already the right final-purge
  implementation and needs no changes — it becomes the thing the grace-period
  job calls, not the thing `DELETE /auth/me` calls directly.

  Needs scoping: whether a pending-deletion account can be used normally
  during the grace period or is read-only/logged-out until the user
  explicitly cancels; whether to email a "deletion scheduled" / "deletion
  cancelled" notice; and how this interacts with the admin panel's own
  delete-user action (same soft-delete grace period, or an immediate hard
  delete for admins, kept as an explicit override).

  **Concrete touch points, from a 2026-07-22 research pass** (file/line refs
  may drift, re-check before implementing):
  1. `models.py`: add `deletion_requested_at: Mapped[datetime | None]` to
     `User` (nullable, no backfill needed — NULL means "not scheduled"),
     near the existing `banned`/`ban_reason` columns (~line 147-148), which
     are the closest existing precedent for an account-state flag. No
     generic `status` enum exists on `User` today — `banned` is the only
     other account-state boolean.
  2. New Alembic migration, nullable-column-add, modeled on the most recent
     migration (`ffffe2b24717_add_email_confirmation_grandfathering.py`,
     the current head) — same `batch_alter_table("users")` /
     `add_column`/`drop_column` shape, `down_revision = "ffffe2b24717"`.
  3. `users/accounts.py`: add `request_deletion(user, db)` /
     `cancel_deletion(user, db)` (set/clear the new column, commit, maybe
     send an email); leave `delete_account` itself untouched — it's called
     by the new purge job and can still be called directly for an admin
     hard-delete override.
  4. `routers/auth.py`: change `DELETE /auth/me` (520-525) to call
     `request_deletion` instead of `delete_account`; add a
     `POST /auth/cancel-deletion` endpoint (or fold into `PATCH /profile`).
     Decide login-time behavior: `login` (246-280) checks `user.banned` at
     259-260 right after password verification and before the
     email-confirmation grace-period gate (261-274, itself a close analog
     of the grace-period logic this feature needs, including its
     machine-readable 403 `detail` string for the frontend) — a
     `deletion_requested_at` check would slot in the same place, either
     blocking login like `banned` or auto-cancelling the pending deletion
     and letting login proceed (product decision).
  5. `users/auth.py`'s `get_current_user` (80-98, the dependency behind
     every authenticated route including `DELETE /auth/me` itself) has the
     same `user.banned` check at 95-96 — mirror there too if pending-deletion
     accounts should be blocked from using the API during the grace period
     rather than just flagged.
  6. `task_runs.py`: add a new `TaskSpec` to the `TASKS` registry (48-93),
     e.g. `TaskSpec("account_purge", "Account purge", "Permanently delete
     accounts past their 30-day deletion grace period.", "Security", 360)`
     — this alone gets it a toggle/interval card in the admin Periodic
     Tasks panel (`routers/admin/periodic_tasks.py`), no admin-UI code
     needed beyond the registry entry.
  7. `social/notifier.py`: there's no general-purpose scheduler in this
     codebase (no APScheduler/Celery) — periodic work is hand-rolled
     `asyncio` loops, one per task, each sleeping on
     `task_runs.get_interval_minutes(key)` and checking
     `task_runs.is_enabled(key)`. The closest existing analog to copy is
     `_email_confirmation_cleanup_loop` (318-332), which purges accounts
     unconfirmed for 14 days by calling `accounts.delete_account` per stale
     row — same shape needed here, filtered on `deletion_requested_at`
     older than 30 days instead. New loop gets registered in the list
     `start_periodic_tasks()` returns (352-361); `main.py`'s `lifespan()`
     (67-84) already starts/cancels every task in that list, no changes
     needed there.
  8. Email notice: no generic mailer module exists — `send_confirmation_email`
     in `users/email_confirmation.py` (76-103) is the only sender, coupled
     to the confirmation-code flow (Brevo, pooled `httpx.Client`, logs
     instead of sending when `BREVO_API_KEY` is unset). A "deletion
     scheduled"/"deletion cancelled" notice needs either a new parallel
     function in that file following the same pattern, or breaking the
     Brevo-send logic out into a generic `send_email(to, subject, text)`
     helper first.
  9. `schemas.py`'s `UserOut` (116-146): expose `deletion_requested_at` so
     the frontend can show grace-period UI (banner, days remaining, cancel
     button).
  10. `routers/admin/users.py`: `delete_user` (1036-1048) calls
      `accounts.delete_account` directly today — decide whether admin
      delete stays an immediate hard delete (likely, as an override) or
      also goes through the soft-delete path. If a pending-deletion state
      should be visible in the admin panel, `_render_user_detail`'s
      `banned_badge` pattern (~236-237) is the existing precedent for a
      status pill, and `_render_account_actions` (163-214) is where a
      "cancel pending deletion" admin action would live.

- **Real phone number confirmation on registration.** Same shape as the
  email-confirmation item above, but there's currently no phone number
  field on `User` at all (`models.py:111-151`) — this needs the field
  added first, plus an SMS-sending capability (no provider integration
  exists yet; candidates like Twilio/Vonage aren't wired up), a generated
  one-time code with expiry, and a verification endpoint accepting
  `phone` + `code`. Open questions: is phone number required at
  registration or optional/add-later; does it replace or supplement email
  confirmation; which SMS provider (cost, coverage — matters if
  international numbers are expected).

- **Anti username-squatter protection.** Prevent usernames from being
  permanently locked up by abandoned/unconfirmed or inactive accounts.
  Overlaps with the "Squatting via never-confirmed accounts" note under the
  email-confirmation item above (periodic cleanup of unconfirmed signups),
  but scope this as its own feature: also consider reserving/releasing
  usernames on account deletion, a cooldown before a freed username becomes
  available again (to stop swap-and-grab abuse), and whether inactive (not
  just unconfirmed) accounts should eventually free their username too.
  Not scoped in detail yet.

## Bugs

- **Block marking future (unaired) episodes as watched — server-side enforcement — fixed.**
  `_assert_not_future_episode()` helper in `routers/media.py` called from both
  `set_episode` (single toggle) and `bulk_episodes` before any `EpisodeWatch` rows
  are written. Raises 422 when the `Episode` catalog row exists and its `air_date`
  is a future date. No catalog row or NULL air_date → allowed (treat as possibly
  aired/untracked). Six tests added to `tests/test_episodes.py`.

- **Show fully up-to-date with aired episodes must not appear in "Watch Next".**
  `list_media()` with `order_by="last_watched"` powers the "Continue Watching"
  list. It must exclude shows where all aired episodes (`air_date <= today`) are
  watched and only future-dated episodes remain. `_sync_progress()` computes
  progress — it may need a companion flag (e.g. `has_unwatched_aired`) that
  `list_media` can filter on, or the filter can be applied directly in the query.
  A show should only re-enter the list once a new episode's air date passes.

- **New aired episodes should rank #2 in "Watch Next".**
  When a tracked show has a newly aired episode the user hasn't watched, it
  should bubble to position #2 in the list (position #1 is the most recently
  actively-watched item — highest `last_watched_at`). Depends on the bug above
  being fixed first — a fully caught-up show must not appear in the list at
  all before this ordering rule is applied. The ordering currently sorts by
  `last_watched` descending; a secondary sort key is needed for shows with at
  least one unwatched aired episode whose `air_date > last_watched_at`.

- **`/auth/me` doesn't expose how many grace-period days an unconfirmed
  account has left.** Flagged from the frontend side (renar-frontend's
  `docs/backlog.md`, 2026-07-30 sweep): `confirm_email_view.py`'s
  `login_reminder`/`login_blocked` copy always shows the *full*
  `SiteSettings.email_confirmation_grace_days` value ("you have 7 days
  left") since the frontend has no way to compute the actual remaining
  count — it knows `days` as a hardcoded mirror constant, not
  `user.created_at`. A `grace_days_remaining`-style field on `UserOut`
  (or folded into the `email_not_confirmed` 403's detail) would let the
  frontend show the real number instead of a static one that's wrong
  from day 2 onward.

## Features

- **Diary endpoint — chronological watch/activity log.**
  New endpoint `GET /diary` returning the user's watch events in
  reverse-chronological order, paginated. Should cover both film/show library
  completions and individual episode watches. Response shape per entry:
  `title_id`, `title` (display name), `poster_path`, `type` (`film`/`episode`),
  `watched_at`, `rating` (nullable), `season`/`episode` (nullable, for episode
  entries). Support query params: `page`, `type` filter, `from`/`to` date range.
  Sources: `episode_watches` and `library_entries` (films and show-level
  completions via `last_watched_at`). Prefer one unified endpoint over two
  separate ones if the schema allows it cleanly.

- **Chronological sort on comments.**
  `GET /media/{id}/comments` currently returns comments in a fixed order.
  Add a `?sort=asc|desc` query parameter so clients can request oldest-first
  (chronological). Default remains the current behaviour; `asc` is the new
  opt-in. Change goes in the comments query in `routers/comments.py` (or
  wherever comments are fetched).

- **Reviews (alongside the existing Comments).**
  Reviews are longer, more considered write-ups — distinct from the casual
  comment thread already in place. Backend work: new `reviews` table + Alembic
  migration, new CRUD endpoints in `routers/`, normalization check in
  `test_normalization.py`. Schema must stay BCNF (a review's rating is a fact
  about the user+title pair, not a copy of anything else).

- **Share — film, show, episode, comment.**
  Backend needs to support shareable deep links or redirect URLs for a title page,
  a specific episode, and a comment (anchor within a thread). Options: generate
  canonical share URLs in the API response, or add a `/share/{type}/{id}`
  redirect endpoint. Decide on a URL scheme before implementing frontend share
  buttons.

- **Social login: Continue with Google / Continue with Apple.**
  Not committed — revisit once real signup-funnel data shows password-registration
  drop-off is a problem worth solving. Would need nullable `google_id`/`apple_id`
  columns on `User` (with nullable `password_hash`), new Alembic migration, new
  `/auth/google`/`/auth/apple` endpoints, `google-auth` + JWKS verification for
  Apple, `GOOGLE_CLIENT_ID`/`APPLE_*` env vars. Apple requires an Apple Developer
  account and is mandatory if Google sign-in is also offered on iOS. Decide on
  native plugin bridge vs. OAuth web-redirect before scoping further.

- **Recommendation feed: infinite-scroll "what to watch next".**
  Not committed — needs design work on what signals feed the taste model before
  scoping endpoints. Would need a "taste inferer" (model/heuristic from watch
  history, ratings, dwell time), new endpoint(s) in `routers/recommendations.py`,
  implicit-signal recording (skip, completion, dwell), and cold-start handling
  for new users. Open question: in-house collaborative/content-based filtering
  vs. external recommendation service.

- **Push notifications (system notifications while the app is closed).**
  `notifier.py`'s `check_new_episodes` only ever writes an in-app `Notification`
  row — nothing reaches the device when the app isn't open. A killed-app
  system notification from a server-side event requires going through the
  OS's push channel (FCM on Android, APNs on iOS); there's no way around
  that requirement on stock Android/iOS. Scoped approach: **OneSignal via
  the `flet-onesignal` PyPI package** (actively maintained, MIT, requires
  `flet>=0.80.0` — no known incompatibility with this repo's `flet==0.85.3`,
  not yet smoke-tested) instead of hand-rolling `firebase_messaging` +
  pubspec overrides — OneSignal hosts the device-token/delivery layer, the
  backend only calls its REST send API. Still required regardless of this
  choice: a Firebase project (Service Account JSON, Android FCM credentials)
  and an Apple Developer account + APNs certificate for iOS — OneSignal sits
  on top of those, it doesn't remove them.

  **Platform scope: Android/iOS/mobile web only, Windows explicitly out.**
  OneSignal's Windows support is WNS-on-UWP only, not the Windows App
  SDK/WinUI3 target a modern Flet Windows build would use — and desktop
  isn't a maintained distribution target for Renar in the first place (see
  the Turnstile-widget desktop gap above), so this isn't worth chasing a
  different provider for. Cost at this scope: free — OneSignal's Free plan
  is unlimited mobile push sends, and web push is free up to 10,000
  subscribers per send (paid tiers only kick in past that subscriber count,
  not from notification volume) — worth revisiting only if/when web push
  subscribers approach that number.

  **Film releases currently generate no notification at all, in-app or
  push.** `check_upcoming_films` (below) only refreshes `Title.release_date`
  for `/upcoming` — it never writes a `Notification` row the way
  `check_new_episodes` does for episodes. Since this backlog item is
  explicitly "new episodes/films", closing that gap (a same-day-of-release
  in-app + push notification, mirroring `check_new_episodes`'s dedupe-by-row
  pattern but keyed on the film releasing rather than an episode airing) is
  part of this item's scope, not a separate one.

  **Decisions locked in during scoping (2026-07-21):**
  - **REST shape:** extend `routers/notifications.py` with `POST
    /notifications/devices` and `DELETE /notifications/devices/{player_id}`
    rather than a new router — same auth dependency, two endpoints don't
    warrant a new file.
  - **v1 kill switch:** none beyond "unset `ONESIGNAL_REST_API_KEY` = feature
    off", matching the existing `brevo_api_key` convention. No `site_settings`
    DB toggle for v1 — a live admin kill switch is a fast-follow, not launch-blocking.
  - **Push call shape:** one OneSignal API call per `Notification` row
    created, fired synchronously right after `db.add(Notification(...))`,
    inside the existing per-show/per-title commit boundary (never batched
    across a whole scan) — a push failure must never block `Notification`
    creation or the notifier loop.
  - **Tap deep-link:** push `data` payload carries `media_item_id` + `kind`;
    the tap handler reuses `notifications_view.py`'s existing
    `title_ctx`/`navigate_safe(page, "/title")` pattern to jump straight to
    the title, not a generic open-to-notifications-list.
  - Confirmed **not** premium-gated — notifications are core tracking
    utility, not a cosmetic perk (see `premium.py`'s existing perk list, all cosmetic).
  - Out of scope for v1: Windows/desktop, live admin kill switch, rich media
    push, retry/queueing on push failure, badge counts, OneSignal
    external_user_id linking, notification quiet-hours.

  **Backend work:**
  - New `DeviceToken` model (`models.py`, after `Notification`): `user_id`
    FK (indexed), `player_id` (`String(64)`, `UniqueConstraint` on
    `player_id` alone — not `(user_id, player_id)`, since a player_id is
    unique per OS-level install and registering it under a different
    logged-in user should move ownership, not duplicate the row),
    `platform` (`"android"`/`"ios"`/`"web"`), `created_at`. One row per
    device, so one-to-many against `User`, not a column on it. New Alembic
    migration (`down_revision` = current head `a4d6e1b8c2f7`), following
    `b2f7a6d391ea_add_import_jobs_table.py`'s template. `users/accounts.py`'s
    `delete_account` needs a new line purging `DeviceToken` rows for the
    user, same FK-safe-order pattern as every other user-referencing table there.
  - `config.py`: `onesignal_app_id`/`onesignal_rest_api_key`, both
    `str = ""` next to `brevo_api_key`, same "empty = disabled, log instead
    of send" convention as `send_confirmation_email`. App ID isn't secret
    (ships client-side); REST key is server-only. Frontend gets its own
    `ONESIGNAL_APP_ID` in `renar-frontend/.env` rather than fetching it from
    the backend, since the SDK needs it very early at page/session setup.
  - New `social/onesignal.py` helper mirroring `users/email_confirmation.py`'s
    Brevo integration line-for-line: pooled `httpx.Client`, `send_push(player_ids,
    title, body, data=None)` that never raises (logs-and-swallows on missing
    key or `httpx.HTTPError`) — callers in `notifier.py` depend on that guarantee.
  - `check_new_episodes` (`social/notifier.py:109-119`) gains a `send_push`
    call right after each `db.add(Notification(...))`, inside the per-item
    loop, before the per-show `db.commit()`.
  - `check_upcoming_films` (`social/notifier.py:131-162`) needs restructuring
    to close the "no film notification at all" gap noted above: shift its
    query from distinct `Title` rows to `LibraryEntry` rows (regaining
    per-user granularity, grouped by `tmdb_id` so one TMDB fetch still
    serves every tracking user, same shape `check_new_episodes` already
    uses), notify only once release day has actually arrived (a
    `RECENT_DAYS`-style window, not on every "coming soon" refresh), dedupe
    via the existing `Notification` unique constraint with a new
    `kind="film_released"` (season/episode stay `NULL`).

  **Frontend work:**
  - Add `flet-onesignal==0.85.*` to `[project.dependencies]` in
    `pyproject.toml` (next to `flet-webview` — confirmed via its own
    `pyproject.toml` that it depends only on `flet>=0.80.0`, no heavy native
    transitive deps the way `flet-web` has, so the dependency-groups
    isolation trick `flet-web` needs shouldn't apply here, but worth a `flet
    build apk` smoke test to confirm before assuming safe). Any Android
    manifest `meta-data` OneSignal needs should go through
    `[tool.flet.android.meta_data]` (a real supported `flet_cli` key) —
    **not** a hand-patch under `build/flutter/android/...`, which is exactly
    the fragility the Turnstile `usesCleartextTraffic` note already warns
    about (edits there aren't source-controlled and vanish on
    `--clear-cache`/a flet version bump/fresh checkout).
  - `api_client.py`: `register_device_token(player_id, platform)` /
    `deregister_device_token(player_id)`, same `_request()` pattern as the
    existing `/notifications` methods (~line 707-725).
  - SDK init in `main.py` near page/session setup (exact `flet-onesignal`
    call names not yet confirmed against the installed package — check
    before writing). Register hooks at two points: `complete_login`
    (`views/auth/auth_views.py:102-147`, the single shared post-login entry
    point for both normal login and post-email-confirm login) and the
    app-start saved-session restore in `main.py` (~268-287), so a device
    re-registers even without a fresh login. Deregister hook at logout
    (`views/profile/profile_view.py:449`) — must fire **before**
    `api.logout()` clears the bearer token, since deregistering needs auth.
  - Tap-to-deep-link: OneSignal's "notification opened" callback reads
    `data.media_item_id` and reuses `notifications_view.py`'s existing
    `title_ctx` + `navigate_safe(page, "/title")` pattern.

  **Backend test plan** (pytest, real DB, happy path + error paths per this
  repo's convention): register/deregister endpoints (happy path, upsert
  moves ownership between two users, wrong-owner deregister is a no-op, 401
  unauthenticated); `check_new_episodes` sends push exactly once per
  notified user with the right payload, a push failure never blocks the
  `Notification` row or rolls back the commit, no `DeviceToken` means no
  error; `check_upcoming_films` creates a `film_released` notification only
  once release day arrives and dedupes on a second run, no notification
  before release (regression guard for existing `/upcoming` behavior);
  `onesignal.send_push` no-ops cleanly with the key unset and swallows HTTP errors.

  **Manual verification needs a real Android device** — FCM token delivery
  is unreliable on emulators. Full device (force-kill app → trigger
  `check_new_episodes`/`check_upcoming_films` → confirm notification arrives
  and tap opens the right title) → logout (confirm `device_tokens` row
  deleted server-side) → uninstall/reinstall (confirm re-login registers a
  fresh row, no error on the stale one) pass needed before shipping. iOS
  pass (TestFlight/ad-hoc + APNs cert) is a stretch goal for the same pass,
  not a blocker for an Android-first ship.

## Infrastructure

- **Domain registered: `breren.com`.** Umbrella domain is bought (done, no
  longer a backlog item). App renamed to Renar; subdomain is `renar.breren.com`.
  Cloudflare DNS (A/CNAME per subdomain, orange-cloud proxy, "Always Use
  HTTPS") still needs configuring; ties into the HTTPS-by-default item below.

- **Wire up HTTPS by default; currently opt-in only.** Caddy-based TLS
  termination was added then dropped (see git history); the current
  approach is documented in `docs/design-decisions.md:298-310` as relying
  on uvicorn's native `--ssl-keyfile`/`--ssl-certfile` flags (see
  README.md:35). No certs, `.env` entries, or docker-compose wiring ship
  by default, so a normal run is still plain HTTP. Needs a default
  cert/TLS setup (or reverse proxy) plus updating the frontend's stored
  base URL scheme once it's on by default.

  **Deployment-specific state (2026-07-19), `api.renar.breren.com`:**
  currently plain HTTP on a non-standard port (8882, port-forwarded to the
  backend's 8000) — not even the usual 80/443. Investigated during the
  Turnstile rollout below and parked rather than rushed:
  - Plain `certbot` HTTP-01 (port 80) is blocked: an unrelated, pre-existing
    service (`Server: Kestrel` — .NET, not this project) already owns port
    80 on that host. Do not touch it without confirming what it is first.
  - This domain's DNS is on Cloudflare (`gerardo.ns.cloudflare.com` /
    `melody.ns.cloudflare.com`), currently in "DNS only" (grey-cloud) mode
    — it resolves straight to the origin's residential IP.
  - Two viable paths, neither started: (a) `certbot-dns-cloudflare` for a
    DNS-01 challenge (needs a Cloudflare API token scoped to "Edit zone
    DNS" for `breren.com`), or (b) — simpler, zero cert management on this
    host — flip the `api` record to Cloudflare-proxied ("orange cloud") and
    set SSL/TLS mode to "Flexible": Cloudflare's Universal SSL terminates
    TLS at their edge for free, origin keeps serving plain HTTP internally.
    Option (b) was the recommendation when this was parked.
  - Until one of these lands, the register screen's Turnstile widget relies
    on `android:usesCleartextTraffic="true"` (see this repo's sibling entry
    below and renar-frontend's `docs/design-decisions.md` "Android APK
    manifest is hand-patched..." entry) — real HTTPS would make that
    manifest patch unnecessary too, not just close this item.

- **Cloudflare Turnstile captcha on `/auth/register` — shipped, a few
  loose ends remain.** Added to combat fake-account registration inflating
  stats/rankings. Live keys configured (`TURNSTILE_SITE_KEY`/
  `TURNSTILE_SECRET_KEY` in `.env`, hostname `api.renar.breren.com`
  registered in the Cloudflare Turnstile dashboard), on/off toggle is a
  live admin Site Settings switch (`site_settings.turnstile_enabled`, not
  an env var — flips instantly, no restart). `/auth/registration-status`,
  `/auth/turnstile-session`, `-widget`, `-callback`, `-token` all send
  `Cache-Control: no-store` (see 2026-07-19 fix — a caching intermediary,
  most likely a mobile carrier's transparent proxy, was serving a stale
  `registration-status`/`turnstile-token` response for several minutes
  after an admin toggle, which for the token-poll endpoint specifically
  could have meant the register screen never seeing an already-resolved
  token). Remaining gaps:
  - **In-memory widget session store (`users/turnstile.py`'s
    `_widget_sessions` dict) doesn't survive a restart or multiple
    workers.** Fine for the current single-process deployment (see the
    "No reverse proxy" design-decision) — a session created just before a
    restart, or landing on a different worker than its later poll/callback
    under a future multi-worker setup, would 404/never resolve. Move to
    Redis or the DB if/when this backend ever runs more than one worker.
  - **Desktop (Windows/Linux) frontend builds silently skip the widget
    entirely** — `flet_webview` has no `WebView` support there at all
    (flet-dev/flet-webview#17). If `TURNSTILE_SECRET_KEY` is set,
    desktop registration will 400 with no client-side warning that a
    check it can't complete is even required. Low priority: desktop
    isn't a maintained distribution target per the frontend README, but
    worth a friendlier client-side message if that ever changes.
  - **Mobile relies on a hand-patched, fragile Android manifest attribute**
    (`usesCleartextTraffic="true"`) to load the widget's `http://` page at
    all — see the HTTPS item above and renar-frontend's
    `docs/design-decisions.md`. Real HTTPS on the backend removes the need
    for that patch entirely, not just the manual-edit fragility.
  - **Email verification — done.** See "Real email confirmation on
    registration" in the Features section above. Captcha alone only stopped
    scripted bulk signups, not a human hand-registering a few throwaway
    accounts; `_compute_ranking`'s percentile denominator and "ahead of me"
    comparison now both exclude unconfirmed accounts.

- **No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`).**
  Distinct from the OTP-sending item above (Brevo, transactional-only, no
  inbox): this is for a real mailbox a person actually reads/replies from —
  support requests, store-listing contact address, domain-registrar
  correspondence. **Zoho Mail free plan** is the pick: up to 5 users, 5GB
  each, free custom-domain mailbox with webmail + IMAP/POP, no card
  required. **Domain: apex `breren.com`, not `renar.breren.com`** — mail
  conventionally lives on the root domain regardless of which subdomain an
  app's API sits on, and this keeps it usable if `breren.com` ever hosts
  more than just Renar. Needs, once the subdomain/DNS work above lands:
  domain verification TXT, MX records (`mx.zoho.com`/`mx2`/`mx3`), SPF/DKIM
  TXT records, optionally DMARC. Not started — same Cloudflare DNS zone as
  the HTTPS/Turnstile items above, so batch with those when DNS is next
  touched.

- **Admin/mod accounts still lack per-account roles.** `routers/admin.py`
  is a working operator dashboard (users, usage, comments, banned IPs)
  gated by a single shared `HTTPBasic` credential pair
  (`settings.admin_path`, admin.py:49) — good for one operator, not for
  granting individual users admin/mod privileges. `models.py:111-151`
  `User` has no `role`/`is_admin` field (only `banned`, `verified`,
  `is_premium`). Needs a role field/table and auth checks gating
  admin/mod-only actions per account if multiple privileged users are
  wanted, distinct from the existing single-operator panel.

- **psycopg3 stale prepared plans after live schema changes.** psycopg3
  auto-prepares statements reused ~5+ times per connection. DDL that alters
  or recreates tables against a pool with existing prepared plans triggers
  `cached plan must not change result type` on the next query using that
  connection. Tests are fixed via `engine.dispose()` in conftest's
  `_fresh_db` fixture. **Production implication: restart/recycle the app
  after running Alembic migrations**, so no pooled connection holds a plan
  against pre-migration table shapes.

## Publishing (app stores, web, going public)

Not yet scheduled. Nothing here is started; capturing the shape of the work
before picking it up. Store-specific build steps (Android/iOS/web packaging)
are tracked in renar-frontend's `docs/backlog.md`.

- **Production hosting isn't chosen or set up.** No Dockerfile/compose file
  exists in either repo and nothing is deployed anywhere. Needs a host
  (Fly.io/Railway/a VPS are all viable) running a persistent Postgres
  (sqlite is fine locally, not for production) with a backup plan, plus
  the app's subdomain on `breren.com` (once picked) and the
  HTTPS-by-default item above wired to point at it.

- **No privacy policy or Terms of Service exist.** Both Apple and Google
  require a live, publicly hosted URL to a privacy policy at submission
  time (Google also wants ToS if the app has accounts/payments). The
  `gdpr-data` folder at the workspace root suggests GDPR is already on the
  radar — this is the point to turn that into an actual published policy
  page, once the app's subdomain is picked to host it on (`breren.com`
  itself is registered already).

- **No data-safety audit done for store submission.** Google Play's Data
  Safety form and Apple's Privacy Nutrition Label both require enumerating
  exactly what user data is collected (email, username, avatar, watch
  history, IP address for rate-limiting) and why. One audit, reused for
  both store listings.

- **Account-deletion page needs a web-reachable path, not just in-app.**
  `DELETE /auth/me` already covers in-app deletion, but Google Play policy
  requires a deletion request to also be reachable *without* installing the
  app (a simple hosted web form/page). Blocked on the app's subdomain
  being picked (`breren.com` itself is registered already).

- **No payment integration wired to the app stores — and mobile can't just
  reuse a web payment flow.** `premium_until` is admin-granted only today
  (see `docs/design-decisions.md:441-450`); there's no Stripe/PayPal/IAP
  integration at all yet. If premium becomes purchasable from inside the
  mobile apps, Apple and Google **require their native in-app-purchase
  systems** for digital subscriptions — routing that through a web checkout
  (e.g. Stripe) inside the app is a store-rejection, not a warning.
  Decide before scoping: (a) wire RevenueCat or raw StoreKit/Play Billing
  for mobile premium, keeping any web-based Stripe flow separate, or (b)
  ship the first store release with premium still admin-granted only and
  add IAP in a later version. Option (b) is the smaller first step.

- **No crash/error monitoring wired anywhere.** No Sentry (or equivalent)
  found in either repo. Worth adding before real (non-dev) traffic hits the
  backend, so a production failure doesn't fail silently — ties into the
  admin-roles and HTTPS-by-default items above as general pre-launch
  hardening.
