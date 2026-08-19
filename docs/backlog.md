[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/08/18 21:31:16.890025 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Known gaps and follow-ups, not yet scheduled.

Every entry is tagged `[Blocking for 1.0]` or `[Future]` right after the
opening `- **`. "1.0" means the next major version bump (first stable/public
release), not the next minor/patch. Resolved entries are deleted outright,
not marked done/fixed — the historical record lives in git history,
CHANGELOG.md, and `docs/design-decisions.md` instead.

## Testing

- **[Blocking for 1.0] Full test coverage across every test type, not just
  the modules that happen to have tests today.** The suite now has every
  commonly-recognized *category* of test set up (unit, integration, smoke,
  regression, contract, property, snapshot, security, load, mutation
  (config only — unverified, no WSL on the dev machine), fuzz), but having
  the category doesn't mean coverage is complete within it:
  - **Contract**: renar-frontend's `test_contract.py` only checks that
    every `ApiClient` call site's `(METHOD, path)` exists in this
    backend's OpenAPI schema. It says nothing about request body shape,
    response body shape, query parameters, or status codes — a renamed
    response field, a changed enum value, or a backend route the frontend
    never calls at all all sail through untouched. Not 100%; closer to a
    routing smoke check.
  - **Property/fuzz**: only cover `schemas.py`'s validators, `models.py`'s
    `normalize_title_key`, and a handful of endpoints
    (`/auth/register`, `/auth/login`, `POST /media`,
    `/auth/confirm-email-session`). Every other router (`comments.py`,
    `premium.py`, `notifications.py`, `upcoming.py`, `stats.py`,
    `imports.py`, `export.py`, `social.py`, `admin.py`, ...) has no
    property or fuzz coverage at all.
  - **Unit/integration**: coverage exists per-router (`tests/test_*.py`)
    but has never been measured — no `coverage.py`/branch-coverage number
    exists to point at. "Every letter of code must be tested" needs that
    measurement first (`pytest --cov`) to know what's actually missing,
    not an assumption from file-per-router existence.
  - **Mutation**: config exists (`pyproject.toml`'s `[tool.mutmut]`) but
    has never actually run (no WSL on the dev machine) and is scoped to
    just `models.py` + `schemas.py`.
  - **Load**: one locust profile (`tests/load/locustfile.py`) covering
    health/me/library/stats/registration-status. No coverage of
    write-heavy paths (comments, ratings, imports) under concurrent load.

  Getting to "full coverage, all test types, 100%" means, in rough order:
  run `pytest --cov` to get a real branch-coverage baseline; write the
  missing unit/integration tests router-by-router until that number is
  actually high (not just "a test file exists"); extend property/fuzz to
  every router with a pydantic-validated request body; turn the contract
  test into real schema validation (response body against the OpenAPI
  response model, not just route existence — `schemathesis` or hand-rolled
  `jsonschema` validation against `app.openapi()` are the two realistic
  options); verify the mutmut config under WSL/Linux CI and widen
  `paths_to_mutate` to the whole `src/` tree; extend the locust profile to
  cover every write endpoint. See renar-frontend's `docs/backlog.md` for
  the matching frontend-side gaps (E2E journeys beyond the one that
  exists, visual coverage beyond the boot screen).

- **[Future] Set up WSL on the dev machine and actually run mutmut.**
  `mutmut` refuses to run at all on native Windows — not a project
  limitation, a hard-coded refusal in the tool itself (`mutmut --help`
  prints "To run mutmut on Windows, please use the WSL" and exits without
  doing anything, pointing at their own open tracking issue,
  github.com/boxed/mutmut/issues/397, for native Windows support that
  hasn't landed). The dev machine has the `wsl.exe` launcher but not a
  working WSL runtime (`wsl --status`/`-l -v`/`--list` all fail with
  `WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED` — the Windows optional feature
  isn't enabled and no distro is installed). Needs: `wsl --install
  --no-distribution` (enables the feature, likely needs a restart), a
  distro (`wsl --install -d Ubuntu` or similar), then `uv`/Python set up
  inside it to actually run `[tool.mutmut]`'s config against this repo.
  Once that's done, the `[tool.mutmut]` config in `pyproject.toml` can be
  verified for real instead of carrying the "unverified" caveat repeated
  in the Testing item above and in `docs/design-decisions.md`.

## Multi-session sync

- **[Blocking for 1.0] Not covered: general data sync (watch status, library, comments,
  notifications).** The `/events` push above is account-settings only.
  Marking an episode watched, adding to the library, posting a comment, or
  a new notification on one session still isn't reflected on another open
  session until it re-fetches on its own (view re-entry, poll, etc.) — no
  push for any of that yet. Extending the same `/events` channel with more
  event types (e.g. `library_changed`) is the likely shape of a fix, but
  scope/priority not decided.

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

### TV Time import

A show with no TMDB match at all now falls all the way back to TheTVDB's
own data (poster, overview, episodes) instead of sitting fully blank —
tracked under `Title.tvdb_id`, upgraded to `tmdb_id` automatically the
moment that resolves. See design-decisions.md's "TheTVDB as a genuine
fallback identity, not just a name source".

- **[Blocking for 1.0] A show already matched elsewhere can still get a second,
  unmergeable `Title` row.** `find_or_create_title` (`catalog/titles.py`) only
  dedups a *new* unmatched row against other unmatched rows sharing the same
  `title_key` (`find_title`'s title-text branch) — it never cross-checks
  against an already-*matched* `Title` stored under different text. So if, at
  import time, TMDB's TVDB-crosswalk lookup, its name search, and every TVDB
  alias retry all fail (a real outage, not a single-request blip — that's
  already covered by `tmdb_get`'s retry/backoff) *and* TVDB itself has nothing
  usable, a fresh unmatched `Title` is created even though the show is already
  tracked under a different name. When it later resolves (periodic retry or
  re-import), `backfill_title_tmdb_id` hits `uq_title_tmdb`, the savepoint
  swallows the collision, and the two rows stay permanently split — same
  failure mode as the pre-fix duplicates, just needing a rarer trigger
  (TMDB+TVDB both down at once) instead of any transient blip. Confirmed still
  live in the current code, not just a pre-fix artifact.

- **[Blocking for 1.0] Minor: concurrent reconciles of the same entry are last-write-wins.**
  Two rows racing to reconcile into the same `LibraryEntry` aren't
  serialized — harmless today since both reconcile functions are monotonic
  (favorite only flips true, rating only fills when empty), but worth a note
  if reconcile logic grows less monotonic later.

- **[Future] Minor: `_progress` entries are never pruned.** Negligible memory; clears
  on process restart. Not worth fixing unless it becomes visible.

- **[Blocking for 1.0] Planned: custom-lists import mapping.** Once the
  "Custom lists" feature (Features below) exists, this importer needs
  read-and-map logic for `lists-prod-lists.csv`.

- **[Future] Planned: "watched on" (streaming source) import mapping.**
  Once the "Watched-on / streaming source tracking" feature (Features
  below) exists, this importer needs matching read-and-map logic:
  `watched_on_episode.csv`/`followed_tv_show_source.csv` (source id per
  episode/show watch — both files are confirmed present in a real GDPR
  export carrying `watched_on_source_id`; the field exists, only the enum
  isn't documented anywhere in the export itself, so its meaning needs
  reverse-engineering, e.g. by cross-checking a few known-source watches in
  a real account against the app's UI). Explicitly decided *not* to build
  in this pass: per-episode emotion reactions (`episode_emotion.csv`,
  `tv_show_user_emotion_count.csv`) — real discrete `emotion_id` values do
  exist in the export (unlike star votes, which don't carry a value at
  all — see above), but adding a whole reaction system duplicates the
  existing 1-100 rating for questionable value, and TV Time's emotion enum
  isn't fully documented from the sample export (only 4 of what's
  presumably ~8 values were observed, no confirmed label mapping).

## Features

- **[Blocking for 1.0] Custom lists.** User-made collections of shows/movies (TV Time has these
  as user-made lists — `lists-prod-lists.csv` in a GDPR export). No
  equivalent model exists yet: needs a `List`/`ListItem` table (or similar),
  ownership, ordering, CRUD endpoints, and UI (create/rename/delete a list,
  add/remove/reorder items, a way to browse a list). Not scoped in detail
  yet — open questions: one list per item allowed or many; public/shareable
  or private-only; does the TV Time importer target this once it exists (see
  the TV Time import section above).

- **[Blocking for 1.0] Expose `MediaItem.release_date` in the media API response.**
  The column exists (`models.py:568`) and is populated from TMDB, but no
  response schema returns it, so the frontend has no way to show a movie's
  or series' release date. Needed for renar-frontend's matching backlog
  entry ("Unreleased titles/seasons/episodes need a clear 'not yet
  launched' indicator, plus a release date") — a not-yet-released item
  (e.g. an upcoming movie added to the library ahead of its premiere)
  needs to show that date on the title page and info page. `Episode.
  air_date` is already used server-side for the unaired-episode guard
  (`routers/media.py`'s `_unwatched_aired_episode_clause`/`_check_episode_
  not_future`) but likewise isn't exposed per-episode for display purposes
  today — check whether it needs adding to the episode response too.

- **[Future] Additional external rating sources (IMDb, Rotten Tomatoes, Metacritic)
  alongside TMDB's `vote_average`.** OMDb (omdbapi.com) is the candidate
  source — a single call returns IMDb rating + vote count, plus Rotten
  Tomatoes and Metacritic scores in its `Ratings` array. Only the IMDb
  entry carries a vote count; RT/Metacritic expose a score with no count
  (neither has a public API of its own, so there's no way to backfill
  that). OMDb looks up by IMDb ID, and `titles.imdb_id` is being added to
  the schema (populated from TMDB's `external_ids`, alongside `tvdb_id`
  and `wikidata_id`) specifically so this lookup doesn't need its own
  title-matching step. Not scoped in detail yet — open questions: caching/
  refresh cadence for OMDb responses, how a second/third rating source
  folds into the existing weighted-mean blend (see `docs/design-
  decisions.md`'s rating-scale entry), and whether RT/Metacritic scores
  (no vote count) should even enter that weighted blend or just display
  alongside it.

- **[Future] Watched-on / streaming source tracking — user priority (2026-07-21).**
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

- **[Future] Ranking only covers total overall watch time; no badges/achievements
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

- **[Blocking for 1.0] Design the registration flow around the email-confirmation toggle
  flipping on/off — user priority (2026-07-29).** The toggle
  (`SiteSettings.email_confirmation_enabled`) and its two bulk-confirm/
  bypass mechanics above were each added reactively, one migration at a
  time (`ffffe2b24717` grandfathering → `1b63409d9417` dropping it for a
  direct bulk `email_confirmed = True` → `6d15f435ffcf` adding
  `email_confirmation_bypassed`), rather than designed as one flow up
  front. Worth a proper pass rather than another one-off patch.

  **What shipped in the 2026-07-29 session** (context for the open
  questions below — see `docs/design-decisions.md`'s "`email_confirmed`
  is authoritative" entry for the full reasoning):
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
  - Docs: this backlog entry, plus a matching entry in renar-frontend's
    `docs/backlog.md` and both repos' `docs/design-decisions.md` — see
    those for the reasoning behind each piece, not repeated here.

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

- **[Blocking for 1.0] Soft delete with a 30-day grace period for account deletion.**
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

- **[Future] Real phone number confirmation on registration.** Same shape as the
  email-confirmation item above, but there's currently no phone number
  field on `User` at all (`models.py:111-151`) — this needs the field
  added first, plus an SMS-sending capability (no provider integration
  exists yet; candidates like Twilio/Vonage aren't wired up), a generated
  one-time code with expiry, and a verification endpoint accepting
  `phone` + `code`. Open questions: is phone number required at
  registration or optional/add-later; does it replace or supplement email
  confirmation; which SMS provider (cost, coverage — matters if
  international numbers are expected).

- **[Blocking for 1.0] Anti username-squatter protection.** Prevent usernames from being
  permanently locked up by abandoned/unconfirmed or inactive accounts.
  Overlaps with the "Squatting via never-confirmed accounts" note under the
  email-confirmation item above (periodic cleanup of unconfirmed signups),
  but scope this as its own feature: also consider reserving/releasing
  usernames on account deletion, a cooldown before a freed username becomes
  available again (to stop swap-and-grab abuse), and whether inactive (not
  just unconfirmed) accounts should eventually free their username too.
  Not scoped in detail yet.

## Performance

- **[Future] `GET /upcoming/history` issues N+1 DB queries and N×M potential TMDB
  calls.** `routers/upcoming.py`'s `get_upcoming_history` loops over every
  tracked TV show and, for each one, calls `sync_show_episodes(db, title)`
  (possibly triggering per-season TMDB fetches if the episode table is cold)
  then runs a separate `db.query(Episode)` filtered to that title — one SQL
  round-trip per tracked show. For a user tracking 50 shows that's 50
  episode queries plus up to N×seasons TMDB calls on a cold cache. The
  background `sync_episode_history` task pre-warms the cache so
  `sync_show_episodes` short-circuits to DB reads in practice, but the
  per-title episode query loop is still N+1. Fix: bulk-load all relevant
  `Episode` rows in one query keyed on `Episode.title_id.in_(title_ids)`,
  group in Python. The `sync_show_episodes` call can stay as-is (it
  short-circuits cheaply when the cache is warm) or be moved to a
  pre-fill step before the loop if the lazy-sync guarantee matters to users
  more than the one-request penalty cost.

## Features

- **[Future] Diary endpoint — chronological watch/activity log.**
  New endpoint `GET /diary` returning the user's watch events in
  reverse-chronological order, paginated. Should cover both film/show library
  completions and individual episode watches. Response shape per entry:
  `title_id`, `title` (display name), `poster_path`, `type` (`film`/`episode`),
  `watched_at`, `rating` (nullable), `season`/`episode` (nullable, for episode
  entries). Support query params: `page`, `type` filter, `from`/`to` date range.
  Sources: `episode_watches` and `library_entries` (films and show-level
  completions via `last_watched_at`). Prefer one unified endpoint over two
  separate ones if the schema allows it cleanly.

- **[Future] Chronological sort on comments.**
  `GET /media/{id}/comments` currently returns comments in a fixed order.
  Add a `?sort=asc|desc` query parameter so clients can request oldest-first
  (chronological). Default remains the current behaviour; `asc` is the new
  opt-in. Change goes in the comments query in `routers/comments.py` (or
  wherever comments are fetched).

- **[Blocking for 1.0] Reviews (alongside the existing Comments).**
  Reviews are longer, more considered write-ups — distinct from the casual
  comment thread already in place. **Restricted feature (2026-08-11
  reassessment): not open to all users** — only a whitelisted set of
  reviewers can post one, so the schema/endpoints need an authorization
  check (e.g. a `can_review` flag or a whitelist table) rather than any
  authenticated user being allowed to create a row. Backend work: new
  `reviews` table + Alembic migration, new CRUD endpoints in `routers/`
  (write endpoint gated to whitelisted users, read endpoints open), and a
  whitelist mechanism (table or user flag — not yet decided), normalization
  check in `test_normalization.py`. Schema must stay BCNF (a review's rating
  is a fact about the user+title pair, not a copy of anything else).

- **[Blocking for 1.0] Share — deep link still needed; frontend shipped without one.**
  renar-frontend's share buttons (title cards, title page, comment tiles)
  ship today generating a branded PNG card (Pillow, client-side) and handing
  it to the native share sheet / clipboard — no link involved, since there's
  no public web frontend hosted yet to link to (see renar-frontend's
  `docs/backlog.md`). This backend half is still open for whenever that
  changes: shareable deep links or redirect URLs for a title page, a
  specific episode, and a comment (anchor within a thread). Options:
  generate canonical share URLs in the API response, or add a
  `/share/{type}/{id}` redirect endpoint. Decide on a URL scheme once
  `renar.breren.com` is actually hosting something to redirect to.

- **[Blocking for 1.0] Per-rewatch ratings, not a single overwritten rating.**
  Ratings are currently one value per user+title, overwritten on every
  re-rate. A rewatch can change a user's opinion (first watch "ok", second
  watch "wow"), so allow a new rating per watch-through instead of only
  replacing the existing one. Needs a rating tied to a rewatch/watch-through
  identity rather than just the title, plus an endpoint to list a user's
  rating history for a title. The title's headline/aggregate score should
  keep using the latest rating per user. Schema must stay BCNF — a rating is
  a fact about the (user, title, watch-through) tuple; check
  `test_normalization.py`. Frontend counterpart in renar-frontend's
  `docs/backlog.md` (rate dialog needs a history view + per-entry editing).

- **[Future] Per-season grading, once a season is fully watched.** No
  season-level rating exists today — only `media_items.rating` (per
  title) and `episode_watches.rating` (per episode); confirmed while
  building the share-card mockups (see renar-frontend's `docs/backlog.md`).
  Wanted: let a user rate a season as a whole once they've finished every
  aired episode in it (mirrors how a title itself gets rated only after
  the user has actually watched it, not before). Needs a new rating fact
  keyed on (user, title, season) — a season isn't its own row anywhere
  today, so this likely means a new table rather than a column bolted onto
  `episode_watches` (which is per-episode) or `media_items` (which is
  per-title, no season dimension). Must stay BCNF; check
  `test_normalization.py`. Open questions: enforce "fully watched" how (all
  aired episodes checked off in that season, computed from
  `episode_watches`), does the aggregate/Renar-average badge described in
  the frontend backlog then read from this instead of leaving seasons
  ungraded, and does this interact with the per-rewatch-ratings entry
  above (a season rewatch re-rating too, or title/episode only). Not
  scoped in detail — not blocking, no urgency signaled.

  Rough API shape, so the frontend side (see renar-frontend's
  `docs/backlog.md`) has something concrete to wire the season-rate
  prompt to: `set_episode`'s response should report whether that write
  just completed the season (all aired episodes in `episode_watches` now
  checked off for that (user, title, season)) — a `season_completed: bool`
  flag alongside the existing response fields — so the frontend knows to
  surface the rate prompt right after that call, without a separate
  round-trip. Reads/writes of the rating itself go through their own new
  endpoint (e.g. `PUT/GET /titles/{id}/seasons/{season}/rating`) rather
  than being bolted onto `set_episode`, since the rating isn't tied to any
  single episode write and needs to be independently re-readable/editable
  later. Important: this flag must reflect *only* whether the season is
  now fully watched, not carry or default to any episode's rating value —
  the frontend backlog entry specifically calls out that the season
  rating must not pre-fill from the last-watched episode's grade.

- **[Future] Social login: Continue with Google / Continue with Apple.**
  Not committed — revisit once real signup-funnel data shows password-registration
  drop-off is a problem worth solving. Would need nullable `google_id`/`apple_id`
  columns on `User` (with nullable `password_hash`), new Alembic migration, new
  `/auth/google`/`/auth/apple` endpoints, `google-auth` + JWKS verification for
  Apple, `GOOGLE_CLIENT_ID`/`APPLE_*` env vars. Apple requires an Apple Developer
  account and is mandatory if Google sign-in is also offered on iOS. Decide on
  native plugin bridge vs. OAuth web-redirect before scoping further.

- **[Future] Recommendation feed: infinite-scroll "what to watch next".**
  Not committed — needs design work on what signals feed the taste model before
  scoping endpoints. Would need a "taste inferer" (model/heuristic from watch
  history, ratings, dwell time), new endpoint(s) in `routers/recommendations.py`,
  implicit-signal recording (skip, completion, dwell), and cold-start handling
  for new users. Open question: in-house collaborative/content-based filtering
  vs. external recommendation service.

- **[Future] Push notifications (system notifications while the app is closed).**
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

- **[Blocking for 1.0] Wire up HTTPS by default; currently opt-in only.** Caddy-based TLS
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

- **[Blocking for 1.0] Cloudflare Turnstile captcha on `/auth/register` — shipped, a few
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

- **[Future] No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`).**
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

- **[Future] Admin/mod accounts still lack per-account roles.** `routers/admin.py`
  is a working operator dashboard (users, usage, comments, banned IPs)
  gated by a single shared `HTTPBasic` credential pair
  (`settings.admin_path`, admin.py:49) — good for one operator, not for
  granting individual users admin/mod privileges. `models.py:111-151`
  `User` has no `role`/`is_admin` field (only `banned`, `verified`,
  `is_premium`). Needs a role field/table and auth checks gating
  admin/mod-only actions per account if multiple privileged users are
  wanted, distinct from the existing single-operator panel.

- **[Blocking for 1.0] psycopg3 stale prepared plans after live schema changes.** psycopg3
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

- **[Blocking for 1.0] Production hosting isn't chosen or set up.** No Dockerfile/compose file
  exists in either repo and nothing is deployed anywhere. Needs a host
  (Fly.io/Railway/a VPS are all viable) running a persistent Postgres
  (sqlite is fine locally, not for production) with a backup plan, plus
  the app's subdomain on `breren.com` (once picked) and the
  HTTPS-by-default item above wired to point at it.

- **[Blocking for 1.0] No privacy policy or Terms of Service exist.** Both Apple and Google
  require a live, publicly hosted URL to a privacy policy at submission
  time (Google also wants ToS if the app has accounts/payments). The
  `gdpr-data` folder at the workspace root suggests GDPR is already on the
  radar — this is the point to turn that into an actual published policy
  page, once the app's subdomain is picked to host it on (`breren.com`
  itself is registered already).

- **[Blocking for 1.0] No data-safety audit done for store submission.** Google Play's Data
  Safety form and Apple's Privacy Nutrition Label both require enumerating
  exactly what user data is collected (email, username, avatar, watch
  history, IP address for rate-limiting) and why. One audit, reused for
  both store listings.

- **[Blocking for 1.0] Account-deletion page needs a web-reachable path, not just in-app.**
  `DELETE /auth/me` already covers in-app deletion, but Google Play policy
  requires a deletion request to also be reachable *without* installing the
  app (a simple hosted web form/page). Blocked on the app's subdomain
  being picked (`breren.com` itself is registered already).

- **[Future] No payment integration wired to the app stores — and mobile can't just
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

- **[Blocking for 1.0] No crash/error monitoring wired anywhere.** No Sentry (or equivalent)
  found in either repo. Worth adding before real (non-dev) traffic hits the
  backend, so a production failure doesn't fail silently — ties into the
  admin-roles and HTTPS-by-default items above as general pre-launch
  hardening.
