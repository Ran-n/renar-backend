[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/09/02 10:57:10.248802 )
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
  - **Property/fuzz**: covers `schemas.py`'s validators, `models.py`'s
    `normalize_title_key`, and a handful of endpoints (`/auth/register`,
    `/auth/login`, `POST /media`, `/auth/confirm-email-session`,
    `POST /comments`, `DELETE /comments/{id}`, `POST /notifications/{id}/read`,
    `DELETE /notifications/{id}`). Every other router (`premium.py`,
    `upcoming.py`, `stats.py`, `imports.py`, `export.py`, `social.py`,
    `admin.py`, ...) still has no property or fuzz coverage at all.
  - **Unit/integration**: coverage exists per-router (`tests/test_*.py`).
    First real baseline measured (`pytest --cov`, default marker set): 82%
    branch coverage. Raised to **96%** in the 2026-09-02 pass, targeting
    every module below ~95%: `users/tvtime_import.py` 68% → 98% (the
    largest single file in the codebase), `tmdb/tmdb_store.py` 69% → 96%,
    `routers/admin/users.py` 77% → 99%, `users/renar_import.py` 76% → 98%,
    `catalog/titles.py` 73% → 86%, `users/security.py` 83% → 95%, plus
    every router/media-util file individually below 95%. While writing
    concurrency-focused tests for that pass, several genuine races
    surfaced and were fixed (not just tested around) — see
    `docs/design-decisions.md`'s entries on `strike_and_maybe_ban`/
    `permaban`'s row locks, the `endpoint_stats`/`request_days` upserts,
    per-user import locking, and the unhandled-`IntegrityError` guards
    added to `auth.py`/`social.py`/`comments.py`/`reviews.py`/`lists.py`/
    `media.py`/`admin/users.py`/`tvdb_store.py`'s concurrent-write paths.
    Remaining real gaps: `catalog/titles.py` (86%), `_devserver.py` (54%,
    OS-level/subprocess code not reachable from in-process coverage),
    `_test_server.py` (0%, invoked only as a subprocess by
    `tests/integration/`, never measured by this instrumented run).
  - **Mutation**: config exists (`pyproject.toml`'s `[tool.mutmut]`) but
    has never actually run (no WSL on the dev machine) and is scoped to
    just `models.py` + `schemas.py`.
  - **Load**: one locust profile (`tests/load/locustfile.py`) covering
    health/me/library/stats/registration-status. No coverage of
    write-heavy paths (comments, ratings, imports) under concurrent load.

  Getting to "full coverage, all test types, 100%" means, in rough order:
  extend property/fuzz to every router with a pydantic-validated request body; turn the contract
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

- **[Future] Minor: `_progress` entries are never pruned.** Negligible memory; clears
  on process restart. Not worth fixing unless it becomes visible.

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

- **[Future] Registration-flow-around-the-toggle: two open product-policy
  questions remain, neither blocking.** The toggle
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

  The toggle-flip race between `register()`'s single read of
  `ss.email_confirmation_enabled` and the admin's bulk-confirm-on-disable
  `UPDATE` was investigated and accepted as a low-probability, bounded risk
  rather than engineered around — see `docs/design-decisions.md`'s
  "Email-confirmation toggle-flip race: accepted, not engineered around."
  Admin visibility into bypassed-vs-confirmed counts (previously an open
  question here) now exists: `routers/admin/users.py`'s "Bypassed
  Confirmation" stat tile.

  Two open product-policy questions remain, neither blocking further
  engineering work:
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
  - **The voluntary "Verify email" tile (renar-frontend's
    `profile_view.py`) is entirely passive** — shown, never surfaced via
    notification/reminder/badge. Decide whether that's sufficient or
    whether bypassed accounts should get any kind of nudge, and if so
    how that squares with "no obligation" being the whole point of the
    tile.

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

- **[Future] Like/dislike (and share) support for Reviews.** `Review`
  (`models.py:1138`) has no engagement columns, unlike comments' `CommentLike`
  (`models.py:1251`, `comment_likes` table — one row per `(comment_id,
  user_id)`, `value` +1/-1, reacting the other way flips the row instead of
  adding a second one). Add the same shape for reviews: a `ReviewLike`
  model/`review_likes` table keyed by `(review_id, user_id)`, plus like/
  dislike endpoints on `routers/reviews.py` matching the comments router's
  shape. Share doesn't need backend work —
  renar-frontend's share cards are client-side image generation, no API
  involved (see its `docs/backlog.md`'s matching entry). See renar-frontend's
  `docs/backlog.md` for the frontend half (like/dislike row + share button
  on each review tile).

- **[Future] Chronological sort on comments.**
  `GET /media/{id}/comments` currently returns comments in a fixed order.
  Add a `?sort=asc|desc` query parameter so clients can request oldest-first
  (chronological). Default remains the current behaviour; `asc` is the new
  opt-in. Change goes in the comments query in `routers/comments.py` (or
  wherever comments are fetched).

- **[Future] Share — add a deep link once the frontend's share cards are
  ready for one.** renar-frontend's share buttons (title cards, title page,
  comment tiles) already ship, generating a branded PNG card (Pillow,
  client-side) and handing it to the native share sheet / clipboard — this
  works standalone today, no link involved, since there's no public web
  frontend hosted yet to link to (see renar-frontend's `docs/backlog.md`).
  This backend half is the add-on for whenever that changes: shareable deep
  links or redirect URLs for a title page, a specific episode, and a
  comment (anchor within a thread). Options: generate canonical share URLs
  in the API response, or add a `/share/{type}/{id}` redirect endpoint.
  Decide on a URL scheme once `renar.app` is actually hosting
  something to redirect to.


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
  the Turnstile item above, so batch with that when DNS is next touched.

- **[Future] Admin/mod accounts still lack per-account roles.** `routers/admin.py`
  is a working operator dashboard (users, usage, comments, banned IPs)
  gated by a single shared `HTTPBasic` credential pair
  (`settings.admin_path`, admin.py:49) — good for one operator, not for
  granting individual users admin/mod privileges. `models.py:111-151`
  `User` has no `role`/`is_admin` field (only `banned`, `verified`,
  `is_premium`). Needs a role field/table and auth checks gating
  admin/mod-only actions per account if multiple privileged users are
  wanted, distinct from the existing single-operator panel.

- **[Future] Log line formatting is hard to read.** Scheduled-job log output
  (`social/notifier.py`'s cleanup/sync/check jobs, `catalog/titles.py`'s
  unmatched-title retry, `tmdb/tmdb_store.py`'s fallback warnings, etc.) is
  plain `logger.info`/`warning` text with no visual structure — scanning a
  run's console output for the handful of lines that matter (warnings,
  counts) among the routine ones is tedious. Worth a pass on the logging
  setup (formatter, color/level distinction, consistent field ordering) to
  make console output easier to skim at a glance. Not urgent — purely a
  developer-experience/readability issue, no functional impact.

## Publishing (app stores, web, going public)

Not yet scheduled. Nothing here is started; capturing the shape of the work
before picking it up. Store-specific build steps (Android/iOS/web packaging)
are tracked in renar-frontend's `docs/backlog.md`.

- **[Blocking for 1.0] Production hosting isn't chosen or set up.** No Dockerfile/compose file
  exists in either repo; the only thing running right now is a single
  residential-machine deployment behind a router port-forward (`api.renar.app`,
  see `docs/design-decisions.md`'s HTTPS entry), not a real host. Needs an
  actual host (Fly.io/Railway/a VPS are all viable) running a persistent
  Postgres (sqlite is fine locally, not for production) with a backup plan.

- **[Blocking for 1.0] Privacy policy and Terms of Service are drafted but not published.**
  `docs/privacy-policy.md` and `docs/terms-of-service.md` exist but are
  both marked DRAFT: `[EFFECTIVE DATE]`, `[HOSTING PROVIDER]`, and
  `[JURISDICTION]` are unfilled placeholders, and neither has had a legal
  review. Both Apple and Google require a live, publicly hosted URL to a
  privacy policy at submission time (Google also wants ToS since the app
  has accounts and comments). Blocked on the app's subdomain being picked
  to host the published pages on (`breren.com` itself is registered
  already).

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
  add IAP in a later version. Option (b) is the smaller first step. If a
  web checkout is added, prefer a merchant-of-record processor (Stripe Tax,
  Paddle, or similar) rather than raw Stripe — it keeps VAT/sales-tax
  collection and PCI card-data scope off Renar entirely.
