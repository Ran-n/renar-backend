[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/07/21 09:51:02.148132 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Known gaps and follow-ups, not yet scheduled.

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

## TV Time import (`routers/imports.py`)

- **Infra failures counted as "skipped" — fixed.** `_upsert_library_entry`
  now returns a fourth `error` flag, set only when its `except Exception`
  fires (a real infra failure), never for an ordinary dedupe skip. Callers
  tally it into a separate `summary["errors"]` counter instead of folding it
  into `skipped`, and [import_view.py](../../renar-frontend/src/renar_frontend/views/library/import_view.py)
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
  written at job start and at completion/failure. `GET /import/tvtime/status`
  falls back to it whenever `_progress` has nothing for the user (a new
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

- **Import coverage panel — added.** [import_view.py](../../renar-frontend/src/renar_frontend/views/library/import_view.py)
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
  episode/show watch — TV Time's `watched_on_source_id` enum isn't
  documented anywhere in the export itself, so its meaning needs
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
  `BREVO_API_KEY` is unset, resend throttle, 14-day cleanup loop) plus
  `routers/auth.py`'s `/auth/confirm-email` and `/auth/resend-confirmation`
  (credential-based, not token-based — an account past the login grace
  period has no token to authenticate with otherwise), `/auth/change-unconfirmed-email`
  (fix a typo'd address before the first confirmation — direct rewrite, no
  old-address approval needed since there's no current owner to protect
  yet), the two-step email-change flow in `update_profile`, and the 7-day
  login grace period before an unconfirmed account is blocked.
  `User.email_confirmed` defaults to `False` for every row including
  existing users. This was built specifically to close the ranking-inflation
  gap noted under the Turnstile item below: `_compute_ranking`
  (`routers/stats.py`) and `app_counters.total_users` (`db_triggers.py`) now
  only count confirmed users. **Grandfathering (migration `ffffe2b24717`):**
  the original "no grandfathering" decision had a real bug — the login
  grace period is measured from `User.created_at`, so any account already
  older than 7 days at migration time got zero actual grace and would be
  blocked at its very next login, silently locking out an entire established
  user base on rollout day. Fixed with `User.email_confirmation_grandfathered`,
  backfilled `True` for every account that existed before this feature
  shipped: exempts the login-gate block and the 14-day cleanup deletion
  permanently, without marking the account `email_confirmed` — it still
  doesn't count toward ranking until it actually confirms, which is the
  entire point. Only accounts created *after* rollout are ever subject to
  the block/cleanup. **Admin kill switch:** `SiteSettings.email_confirmation_enabled`
  (Site Settings page, same pattern as `turnstile_enabled`) — off skips the
  code step for new registrations entirely and immediately bulk-confirms
  every currently-unconfirmed account (so nobody stays silently excluded
  from ranking or blocked at login once the feature is off); the settings
  page also surfaces a warning when `BREVO_API_KEY` is unset, since that's
  the reason codes aren't actually being emailed yet. Not yet done: real
  sending is still off (`BREVO_API_KEY` unset) pending the subdomain/DNS
  work in the Infrastructure section; the Brevo bounce/complaint webhook;
  and the admin panel has no live toggle for the grace-period/cleanup
  windows (currently fixed constants in `users/email_confirmation.py`).

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
