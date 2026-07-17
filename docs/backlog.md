[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/10 13:55:42.476296 )
[//]: # (+ Revised: 	2026/07/18 00:26:59.571389 )
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
  ([import_view.py](../../renar-frontend/src/renar_frontend/views/import_view.py))
  renders as "Import complete ✓" with all-zero counts.

- **Minor: concurrent reconciles of the same entry are last-write-wins.**
  Two rows racing to reconcile into the same `LibraryEntry` aren't
  serialized — harmless today since both reconcile functions are monotonic
  (favorite only flips true, rating only fills when empty), but worth a note
  if reconcile logic grows less monotonic later.

- **Minor: `_progress` entries are never pruned.** Negligible memory; clears
  on process restart. Not worth fixing unless it becomes visible.

## Features

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
  **badge/achievement system** — unlockable badges for specific
  accomplishments (e.g. finishing a franchise, a binge streak, watching
  N hours of a genre) — doesn't exist at all yet: no `Achievement`
  table, no per-user unlock rows, no UI for it. This is a real departure
  from the current badge design, which is explicitly "one derived badge,
  never a stored list" (see `docs/design-decisions.md`). Needs scoping:
  which per-category rankings to add first, and what the badge set /
  unlock conditions look like.

- **Real email confirmation on registration.** `routers/auth.py:86-107`'s
  `register` endpoint creates the `User` row immediately after checking
  username/email uniqueness — no email ownership check happens at all, so
  anyone can register with an email address they don't control. Note
  `models.py` already has a `verified`/`verification_requested` pair on
  `User`, but that's the existing admin-approved "verified" *badge* (see
  `admin.py:962-1013`) — a distinct concept from email-ownership
  confirmation; this needs its own field(s) (e.g. `email_confirmed`), not
  reuse of that one. Fully scoped and decided; sender address will be
  `noreply@renar.breren.com` (app renamed to Renar, subdomain `renar.breren.com`
  decided — see `renar/common` branding notes) — build the rest now with
  the send stubbed/logged. Decisions:

  - **Provider: Brevo.** Free tier is 300 emails/day with no separate
    monthly cap (vs. Resend's cleaner API but 100/day *and* 3,000/month
    combined cap) — the uncapped daily headroom won over Resend's nicer
    DX for this low-volume use case. Needs `BREVO_API_KEY` added to
    `.env`/`config.py`, no account created yet.
  - **Wait for the subdomain name before wiring real sends.** Without a
    verified sending (sub)domain, Brevo requires verifying a single sender
    mailbox instead — sending "from" e.g. a personal Gmail address through
    a third-party API commonly gets rejected/spam-foldered by Gmail's own
    DMARC enforcement, since Brevo isn't an authorized sender for
    `gmail.com`. Build everything else now (token generation, endpoints,
    gating, migration) with the send call logging the would-be email
    content instead of actually sending, so it's ready to flip on the
    moment DNS (SPF/DKIM/DMARC) for the app's actual subdomain on
    `breren.com` is in place.
  - **UX: 6-digit one-time code, entered in-app** — not a clickable link.
    renar-frontend has no Android App Links / custom-URL-scheme config
    (confirmed via grep), so a link opened from the Gmail app would just
    land in a browser tab, disconnected from the installed Flet APK. A
    code sidesteps that deep-linking work entirely.
  - **Code storage: DB-stored, hashed, with an expiry column** — not a
    stateless JWT. Needs to be single-use and revocable (invalidated on
    resend), which a JWT can't do cleanly. Confirm endpoint must be
    idempotent (confirming an already-confirmed account is a no-op, not
    an error).
  - **Email normalization: lowercase + strip**, applied on write and on
    every uniqueness/lookup comparison in both `register` (`auth.py:93-98`)
    and `update_profile` (`auth.py:148-151`). Closes the `Foo@x.com` vs.
    `foo@x.com` duplicate-account gap. (Not folding Gmail dot/plus
    addressing — ruled too aggressive/edge-case-heavy for now.)
  - **Email-change flow: two-step, not a silent swap.** `PATCH /profile`'s
    email change (`auth.py:138-151`) must first send a confirmation to
    the *current* (old) email authorizing the change, then treat the new
    address like a fresh signup — full code verification before it's
    considered confirmed. `email_confirmed` flips to `False` the moment
    the new address is set and stays `False` until it completes its own
    code verification.
  - **Resend-code abuse: reuse the existing login throttle.**
    `security.py:247-282`'s `check_login_allowed` already implements the
    needed mechanism — in-memory sliding-window counters keyed per-account
    and per-IP, gated by `settings.abuse_guard_enabled`. Reuse the same
    deque/prune pattern for the resend endpoint rather than building a
    second limiter.
  - **Never-confirmed cleanup: delete after 14 days.** A scheduled job
    removes `email_confirmed=False` accounts older than 14 days, freeing
    squatted usernames/emails that would otherwise sit unclaimed forever
    (uniqueness is checked at registration regardless of confirmation
    status).
  - **Migration: force re-confirmation for existing users**, not
    grandfathering. The new column defaults every row — old and new — to
    `email_confirmed=False`; existing accounts have to go through the
    same code-verification flow as new signups. (Deliberate override of
    the usual "don't retroactively lock out established accounts"
    instinct — confirm this is still wanted once the login-gating grace
    period below is live, since it means *every* current user hits that
    grace-period clock at once on rollout.)
  - **Login gating: blocked only after a grace period.** Login isn't
    blocked immediately for unconfirmed accounts, but after a grace
    period expires without confirmation, login is refused until the
    account confirms. Assumed default: **7 days** (shorter than the
    14-day cleanup deletion, so nobody gets deleted before ever being
    blocked) — flag if a different window is wanted. Also gate any
    future password-reset-via-email flow (doesn't exist yet) and premium
    purchase (`User.premium_until` implies monetization) on
    `email_confirmed`, since both involve either account recovery or
    real money tied to an address that might not be owned by the account
    holder.
  - **Admin visibility: add a pill now.** `admin.py`'s user list
    (`_render_users`, `admin.py:551-599`) and per-user detail view
    (`admin.py:1089-1142`) already show `banned`/`verified`/`premium_until`
    pills (`_premium_pills`, `admin.py:950-989`) — add an "email
    confirmed" pill alongside them in the same pass, not deferred.
  - **Delivery observability: log now, webhook later.** Log send
    failures immediately (the send must be `BackgroundTasks`-based, same
    idiom as `warm_title_translations` in `routers/media.py:115`, so a
    provider outage never blocks registration itself); defer wiring
    Brevo's bounce/complaint webhook until real sending is live, since it
    can't be tested against a stub anyway.
  - **Localization: reuse `User.language`.** Small per-locale string
    table for the code email, falling back to English for unsupported
    languages — matches the app's existing per-user localization bar
    (see the title-localization architecture notes) rather than shipping
    English-only.

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
