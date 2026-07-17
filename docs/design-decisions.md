[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:10:01.809974 )
[//]: # (+ Revised: 	2026/07/18 00:26:59.749038 )
[//]: # ( ---------------------------------------------------------------------- )

# Design decisions

Non-obvious architectural and tuning choices, grouped by area, with the
reasoning behind each so future changes don't accidentally re-break the
original problem. Day-to-day usage docs are in the [top-level README](../README.md);
`.env` reference in [environment-variables.md](environment-variables.md).

## Data model

### Titles vs. library entries

`titles` holds the shared, catalog-sourced facts about a film/show/book/video
(title, year, poster, genres, TMDB id) — one row no matter how many users
track it. `library_entries` (formerly `media_items`) holds one user's
personal state against a title: status, rating, notes, progress, favorite.

**Why:** ratings, comments and "how many people are tracking this" are
naturally community-scoped (per title), not per-tracking-row. Keeping
catalog metadata on the entry would mean N duplicate copies of the same
poster URL for N users, and updating a title's metadata would require a
bulk update across every user's row instead of one write.

### Title identity: `tmdb_id`, falling back to a normalized key

A title's identity is its `tmdb_id` when TMDB has a match; otherwise a
normalized `title_key` derived from the entered title. This lets manually
entered items (YouTube videos, books without an Open Library match) still
dedupe and share a `Title` row across users, instead of every user's manual
entry creating its own untracked title.

### Normalized schema, enforced by a guard test

The schema is kept normalized (3NF for everything user- or catalog-shaped):
genres are `genres` rows linked through the `title_genres` association table
(never a comma-joined string), comments reference their `titles` row by
`title_id` FK (never re-stored `media_type`/`tmdb_id`/`title_key` copies),
and per-user usage counters (`login_count`, `last_login_at`,
`request_count`) do not exist as columns — they are derived from
`login_events` / `request_days` / `endpoint_stats` at read time.

**Why:** every one of those denormalizations existed once and caused the
classic anomalies — genre stats needed string-splitting, a comment thread
and its title could disagree about identity, and the login counter could
drift from the login event log (it did: one pre-`login_events` login was
unrecoverable at migration time).

**Enforcement:** `tests/test_normalization.py` fails the suite when a
`*_id` column has no FK, a count/total-shaped column is not registered with
a justification, a plural-named string column appears, a column duplicates
one reachable through the table's own FK, or any of the cured
denormalizations returns. Each rule is a mechanical proxy for a specific
textbook normal form — see the module docstring for the mapping — rather
than a house style invented independently of it:

- 1NF (atomic values): no plural-named string columns (`titles.genres` once
  held `"Drama, Crime"`; now `title_genres` links to `genres` rows).
- 2NF/3NF/BCNF (every non-key attribute depends on the whole key, and only
  the key): `test_no_copied_columns_across_foreign_keys` flags any column
  whose name also exists on a table reachable through one of this table's
  own FKs — the schema-level signature of a value copied from (or
  derivable through) another row instead of being an independent fact
  about this one. This is what would have caught `comments.tmdb_id`
  duplicating `titles.tmdb_id` before it was cured.

The registered exceptions are deliberate, not loopholes:
`endpoint_stats.count` / `request_days.count` / `strikes.count` are *bounded
upsert counters* whose normalized form would be an unbounded per-request log
(worse, by design — see Anti-abuse); `library_entries.episodes_watched`
is user-asserted coarse progress that is only *derived* (one write path,
`_sync_progress`) when per-episode rows exist; and `ALLOWED_COPIED_COLUMNS`
covers same-named columns that are genuinely different facts (e.g.
`episode_watches.rating`, a per-episode rating, vs. `media_items.rating`,
the show's overall rating) or a deliberate, documented redundancy (e.g.
`notifications.user_id` duplicating `media_items.user_id`, needed because
`media_item_id` is nullable so the recipient can't always be derived
through it). Widening any allowlist is a design decision and belongs in
this file.

Facts cached from an *external* system (TMDB's `next_episode_air_date`,
`release_date`, etc. on `titles` — see [`/upcoming` reads pre-synced Title
columns](#upcoming-reads-pre-synced-title-columns-never-fetches-tmdb-live))
are not a normalization concern at all: they depend on the whole of
`titles.id` and nothing but `titles.id`, which is exactly what 3NF
requires. Staleness of an external cache and redundant storage of *our
own* data are different properties — the guard test only polices the
latter.

### `users.total_watch_minutes`: a stored aggregate, maintained by a database trigger, not application code

The watch-time leaderboard (`/stats/ranking`) needs every user's total
watch minutes to compute rank. Deriving that at read time means scanning
every user's library on every ranking request; caching it (in memory, on
a timer) means either a background job that runs whether or not anyone's
using the app, or an unlucky request eating a live recompute when the
cache expires. Both were tried and rejected in favor of storing the
total on `users.total_watch_minutes` (migration `a7c2e9f4b816`), so a
read is just an indexed `COUNT`.

**Why this doesn't repeat the `login_count` mistake:** the whole reason
per-user counters are normally derived at read time (see above) is that
a *previous* stored counter drifted from the truth because application
code was responsible for keeping it in sync and a code path didn't.
`total_watch_minutes` carries the identical drift risk if it's
maintained the same way — so it isn't. A Postgres trigger on
`media_items` (fires on insert/delete, and on update only when
`status`/`episodes_watched`/`user_id` actually changed) and on `titles`
(fires when `runtime_minutes`/`total_episodes` changes, fanning out to
every user with that title in their library) recomputes the affected
user's total atomically, in the same transaction as the write. There is
no "remember to call the recompute function" step for a future write
path to omit — the column can't drift from `media_items`/`titles`
because nothing can change those tables without the trigger running.

**Trade-off accepted:** the aggregation logic now exists in two forms —
the SQL inside the trigger functions, and `_total_watch_minutes_by_user`
in `routers/stats.py` (kept only as an independent check the tests use to
verify the trigger got it right, not called from request-time code).
Adding a second ranking metric means writing its own trigger, not just a
Python callable — more upfront cost than the derive-at-read-time default,
justified here by how often `/stats` and `/stats/ranking` are hit.

### `site_settings`: a singleton row for runtime-tunable settings

All twelve anti-abuse tunables and the two registration flags (`registration_open`,
`invite_only`) live in a `site_settings` singleton row (`id` always `1`,
`CHECK`-constrained, same pattern as `app_counters`) so the admin panel can change
them without a server restart or an `.env` edit.

`src/renar_backend/site_settings.py` exposes three callables:

- `get_site_settings(db)` — reads or creates the row; on first call it seeds
  it from the corresponding `config.py` / `.env` defaults so existing deployments
  keep their tuned values (upsert-on-read bootstrap, never an explicit `INSERT`
  at startup).
- `current()` — 5-second TTL in-process cache used by `AbuseGuardMiddleware`
  (which runs on every request) to avoid a DB hit per request.  The admin POST
  handler calls `invalidate()` after committing so the new values take effect
  within the TTL, not just after it expires.
- Defensive fallback: if the `site_settings` table doesn't exist yet (migration
  not run, fresh checkout) `current()` falls back to the config defaults and
  retries on the next call — the same pattern `security.py` uses for
  `_load_permabans`.

**Why a singleton, not individual settings rows:** the whole table is read as one
object on every call — an `id → value` key/value store would still do one read
(WHERE id IN (...)), but a typed ORM model gets IDE support, migration-tracked
schema, and column-level constraints for free.  The `id = 1` check constraint
prevents accidental second rows from misuse of the upsert path.

### Invite-only registration

When `site_settings.invite_only` is `true`, `POST /auth/register` requires a
valid `invite_code`.  Validity: not revoked, `uses < max_uses` (or `max_uses IS
NULL` for unlimited), and `expires_at` is `NULL` or in the future.

The `FOR UPDATE` lock on the `invite_codes` row before reading `uses` serializes
concurrent registrations with the same code — without it two simultaneous signups
could both read `uses = 0`, both pass `< max_uses = 1`, and both succeed,
producing two users from a single-use invite.  The use increment and the new user
row commit in the same transaction, so a crash can never consume a slot without
creating the user.

`max_uses IS NULL` means unlimited uses (a "join us" link).  The original
migration (`b9c3e1f84a2d`) created `max_uses` as `NOT NULL`; a follow-up
(`ae65f1be8d32`) immediately made it nullable.  The model has **no Python-side
default** for `max_uses` — a `default=1` would silently override an explicit
`None` at flush time, so every caller passes the value explicitly.

### `app_counters.total_users`: the same pattern, for a different reason

`/stats/ranking`'s percentile needs `total_users` (the denominator)
alongside each user's rank. The obvious implementation —
`SELECT COUNT(*) FROM users` on every ranking request — has a property
that's easy to miss: `COUNT(*)` has no O(1) shortcut in Postgres, index
or not. MVCC means visibility must be checked per row, so counting the
whole table gets slower in direct proportion to how many users exist,
forever, on every single ranking read. This doesn't show up at small
scale (a seq scan over a few dozen rows is instant) — it's the kind of
cost that's invisible until the table is large, then becomes the
dominant cost of the endpoint.

`app_counters` is a singleton row (`id` is `CHECK`-constrained to always
be `1`) holding `total_users`, kept current by a trigger on `users`
(`AFTER INSERT OR DELETE`, incrementing/decrementing by exactly 1 — see
migration `a7c2e9f4b816`), same reasoning as `total_watch_minutes` above:
maintained atomically by the database, not by application code that
could forget to call an increment somewhere. Reading it is a single
primary-key lookup, `O(1)` regardless of how many users exist.

**Why a singleton row isn't a hot-lock problem:** every registration and
every account deletion serializes on updating that one row — a real
contention point if it happened at the same rate as, say,
`total_watch_minutes` updates (which fire on every watch action, from
every user, constantly). Account creation/deletion is orders of
magnitude rarer than that, by nature — nobody registers or deletes
their account repeatedly per second the way they mark episodes watched.
The same singleton-row pattern would be the wrong call for a
counter that changes as often as user activity does; that's exactly why
`total_watch_minutes` is a per-row counter (one row per user, no shared
lock across users) rather than a single site-wide total.

**Table creation ordering:** `app_counters` has no foreign key to `users`
(it's not a per-user fact), so SQLAlchemy's dependency-based table
creation order has nothing to anchor it to. `models.py` declares this
explicitly with `AppCounters.__table__.add_is_dependent_on(User.__table__)`
— the tool SQLAlchemy provides specifically for "must be created after,
but there's no real foreign key" — rather than relying on incidental
ordering that isn't actually guaranteed.

### Ranking at large scale: what's built, what's deferred, and why

The trigger-maintained columns above make `/stats/ranking` O(1) for the
value itself and O(k) (k = users ahead of the viewer, via an index-only
scan) for rank — a deliberate stopping point, not the ceiling of what's
possible. Three further concerns were identified and intentionally left
as documented plans rather than built speculatively, because each
requires either infrastructure this repo doesn't provision or real
production numbers this app doesn't have yet. Building any of them now
would mean guessing at a shape (partition scheme, replica topology,
bucket granularity) against data that doesn't exist.

**Write throughput / WAL.** Each trigger firing is O(1), but at very
high concurrent write volume the bottleneck stops being any individual
query and becomes Postgres's write-ahead log — every transaction, however
small, appends to one serial log, so throughput eventually becomes
WAL-bound regardless of how cheap each write's own logic is. Two levers,
both Postgres/deployment configuration rather than application code (no
`postgresql.conf`, connection-pool config, or other infra file exists in
this repo to hold them):
- `synchronous_commit = local` or `off` trades a few ms of
  worst-case durability (data since the last flush, lost only on a hard
  crash) for meaningfully higher write throughput — a reasonable trade
  for "marked an episode watched," not for anything that must never be
  lost.
- Connection pooling (PgBouncer) — standard, far smaller a lift than
  anything below, and worth having independent of ranking specifically.

**Table size (`media_items`/`titles`).** At hundreds of millions to
billions of rows, B-tree lookups still scale logarithmically (not a
correctness concern), but *maintenance* — VACUUM duration, index
bloat — stops being tractable on one undivided table. Plan: hash-partition
`media_items` by `user_id` once that's an observed problem (`pg_stat_user_tables`
showing VACUUM taking too long, or index bloat trending up), not
preemptively — nearly every query already filters `WHERE user_id = X`,
so partition pruning would apply almost for free once partitioned. Doing
this on a table with a few dozen rows would mean picking a partition
count/scheme with no real data to size it against.

**Single point of failure.** One Postgres primary serving all reads and
writes is a ceiling regardless of query-level optimization. Plan:
streaming replication, with staleness-tolerant read traffic (`/stats/ranking`,
`/stats` overview — a leaderboard doesn't need read-your-writes
consistency) routed to a replica while writes stay on the primary.
Requires provisioning a second database instance, which is an operations
decision, not a code change available inside this repo.

**What would actually trigger building any of this:** production
numbers, not a guessed row-count threshold. `EndpointStat` (existing
usage-tracking table, see `UsageTrackingMiddleware`) currently records
request *counts* per route, not latency — there is no signal today that
would show `/stats/ranking` getting slow before users start noticing it.
Adding latency tracking (even just a p95/p99 sample per route) would be
the first real step toward knowing *when* any of the above is actually
needed, rather than guessing.

### Every FK queried on its own carries an index

Beyond the composite unique constraints, each foreign-key column that is
filtered on by itself has a plain btree index — including the "reverse
reference" scans: `users.avatar_id`, `users.background_id`,
`media_items.custom_poster_image_id`, `media_items.custom_backdrop_image_id`,
`episode_custom_stills.still_image_id`, and `external_images.image_id`
(all six counted by `gc_image()` on every image-attach or image-clear),
`notifications.media_item_id` (scanned by the ORM cascade whenever a
library entry is deleted) and `title_genres.genre_id` (the composite PK
only serves title-first lookups).

**Why:** Postgres does not index FK columns automatically, so every
un-indexed FK turns the referencing-side lookup into a sequential scan —
invisible at dev-data sizes, a per-write tax at real ones. The rule keeps
the decision mechanical: a new FK either gets an index or a written reason
why no query ever filters on it alone.

### Comment replies: adjacency list, whole-subtree cascade delete

Replies are ordinary `comments` rows with a self-referential `parent_id`
(arbitrary nesting depth). `GET /comments` returns only top-level rows
with replies nested under `replies` (loaded via the ORM relationship,
which walks `parent_id` alone — never the scope columns), chronologically.
Deleting a comment (owner or admin) deletes its entire reply subtree.

**Why:** an adjacency list is the simplest tree encoding that supports
"reply to a reply, and so on" without a depth cap, and thread sizes here
(≤100 top-level rows per target) don't justify materialized paths.
Cascade delete over orphaned "deleted" placeholders keeps the model free
of tombstone state; a reply without its context is worthless anyway.

### Only root comments store title_id/season/episode; replies derive it

`title_id`/`season`/`episode` used to be copied onto every reply so a
thread's rows could all be found by scope alone. That was a transitive
dependency through `parent_id`: a reply's scope is a fact about its thread
root, not independent data about the reply row itself, so a copy on every
row violated BCNF (every non-key attribute must depend on the whole key,
and nothing but the key — see [Normalized schema, enforced by a guard
test](#normalized-schema-enforced-by-a-guard-test)). Only root comments
(`parent_id IS NULL`) carry these columns now (`title_id` is nullable);
`comment_threads.resolve_root_scope()` derives them for a reply with a
recursive `parent_id` walk (a Postgres recursive CTE), used by the reply
"same thread" validation in `POST /comments` and the admin comment table's
target column.

**Why:** the copy only ever existed to let a scope-based query return
replies directly, but nothing does that — `GET /comments` queries roots
by scope and lets the ORM `replies` relationship walk `parent_id` for the
rest, so the copy was pure redundancy, not a real requirement. The
trade-off is an extra recursive query in the two places that need a
reply's scope explicitly (previously an O(1) column read); both are
low-traffic paths (one validation per comment created, one render per
admin page view), not the hot `GET /comments` read path.

### Comment reports: one row per (comment, reporter), resolved by deletion

`POST /comments/{id}/report` upserts nothing and stores no state machine:
one `comment_reports` row per reporter (repeat reports are no-ops), own
comments cannot be reported, and the admin comment manager shows a per-
comment report count. `DELETE /comments/{id}/report` lets the reporter
retract their own report (a no-op if none exists, mirroring unlike).
Admin-side, "resolving" a report is deleting the comment (which cascades
its reports) — there is no dismiss/ack workflow.

**Why:** the report is a moderation *signal*, not a ticket; at this scale a
count next to the comment in the existing admin table is the whole
workflow, and the unique constraint keeps one user from inflating it.

### Account deletion has exactly one purge path (`accounts.delete_account`)

Self-service deletion (`DELETE /auth/me`) and the admin panel's delete-user
action call the same `accounts.delete_account()`. The helper clears every
row referencing the user in FK-safe order and deletes the user's comments
*one by one through the ORM* — never with a bulk `DELETE` — so each
comment's relationship cascades (likes, reports, the whole reply subtree)
actually run.

**Why:** the two endpoints used to carry hand-copied variants of this
cleanup, and the copies drifted: the self-service variant bulk-deleted
comments (bulk deletes bypass ORM cascades), so an account whose comments
had replies or reports from other users — or that had reported someone
else's comment — failed deletion with an FK violation. Any new
user-referencing table gets added to the shared helper once, not remembered
twice.

### Content-addressed image store (`storage.py`)

Uploaded/cached images (avatars, cached posters, book covers) are stored by
the BLAKE3 hash of their bytes, in a git-style two-level directory fan-out
(`media/images/<hash[:2]>/<hash[2:4]>/<hash>.jpg`).

**Why:** identical content (the same poster fetched for two different users,
or a re-uploaded avatar) is stored exactly once. The two-level fan-out keeps
any single directory from accumulating thousands of entries, which degrades
listing performance on most filesystems.

### Postgres via `DATABASE_URL`; schema owned by Alembic

The app never creates tables itself — every schema change is an Alembic
migration.

**Why:** Alembic-owned schema means `git log` on `alembic/versions/` is a
complete, reviewable history of every structural change — there's no
implicit "the app just fixes it up on startup" behavior to reason about.
The project ran on SQLite early on and migrated to Postgres once multiple
concurrent writers (the parallelized TV Time import) needed real
transactional isolation; SQLite support has since been removed.

## Anti-abuse

The rate-limiting/banning system's five layers and their specific thresholds
are documented in full in [anti-abuse.md](anti-abuse.md) — this section only
covers the *shape* of the design, not the tuning.

### In-memory counters, persisted permabans

Request-rate counters and short-lived temp-ban state live in a process-local
dict/deque. Permanent bans (honeypot hits, strike threshold reached) persist
to the `banned_ips` / `strikes` tables.

**Why:** counters that reset on every restart are fine for temporary bans —
a scanner that gets lucky with a restart just re-earns its ban within
seconds. But losing a *permanent* ban on every deploy would mean actively
malicious IPs get a clean slate on every release. The `strikes` table is the
compromise: escalation history survives restarts, but the hot-path counters
that would otherwise need a DB round-trip per request stay in memory.

**Caveat:** if this ever runs as multiple worker processes, the in-memory
half needs to move to Redis or similar — see the note at the top of
`security.py`.

### Per-account login backoff, not just per-IP

Failed-login tracking has two independent trackers: per (account, IP), and
per account across all IPs.

**Why:** many real users share one IP (an office, a mobile carrier's CGNAT
pool). A pure per-IP lockout would let one distributed credential-stuffing
attack (many IPs, one target account) through, while a naive shared-IP
lockout would collateral-damage everyone behind that IP for one person's
typos. The two trackers cover both attack shapes without either failure mode.

### `/svc/bans` + `/svc/strikes` share ban/strike state with the frontend, not a separate DB for it

`renar-frontend`'s own web server (`uv run web`) is internet-facing and
gets scanned independently of this API — the guard here has no visibility
into traffic that never reaches it. Rather than give that process its own
Postgres access, its scaled-down anti-abuse guard (frontend `anti_abuse.py`)
pushes/pulls permabans *and* temporary strikes through three M2M endpoints
here, guarded by `INTERNAL_SERVICE_SECRET` (see
[anti-abuse.md](anti-abuse.md#sharing-bans-with-the-frontend)). `strike_and_maybe_ban()`
and `load_active_temp_bans()` in `security.py` had their leading underscore
dropped specifically so `routers/svc.py` could reuse them rather than
reimplement the same escalation logic for a second surface.

**Why not `/internal/...`:** that prefix is already honeypot bait (see
`HONEYPOT_PREFIXES`) — a real route there would permaban the frontend the
moment the secret was misconfigured. `/svc/` was picked specifically to not
collide with any existing or planned honeypot path.

**Why 404 instead of 401/403 on a bad secret:** matches the honeypot
posture elsewhere in this file — an unauthenticated prober should see no
evidence the route exists at all.

### Admin panel: server-rendered HTML behind HTTP Basic, not a JSON API + SPA

`/admin` renders HTML directly from FastAPI rather than exposing admin data
as JSON for a separate frontend to consume.

**Why:** it avoids building and shipping a second frontend for a feature
only the operator uses, and keeps the public JSON API free of
admin-only routes that would otherwise need their own auth scheme layered
onto the JWT system. The tradeoff (no rich client-side interactivity) is
acceptable for an infrequently used internal tool.

### Admin panel colors mirror the app's Gruvbox palette

Every color in the admin CSS comes from the same Gruvbox values the app
theme defines (frontend `themes.py` `GRUVBOX`): the `bg0`–`bg3` ladder for
surfaces/borders, `fg`/`fg_dim` for text, and the bright accents
(`#fabd2f` yellow, `#fe8019` orange, `#fb4934` red, …) — not the faded
variants and never off-palette values.

**Why:** the panel is part of the same product; using one palette keeps it
visually consistent with the app, and pinning to the named values in
`themes.py` gives a single source of truth to check new admin CSS against.

### `ADMIN_PATH` is configurable, and the default becomes a honeypot

Moving the admin panel off `/admin` is the primary defense for that
endpoint (HTTP Basic alone doesn't rate-limit password guesses the way the
login endpoint does). Once moved, the *original* `/admin` path is added to
the honeypot list automatically — nothing legitimate should ever request it
again, so any request there is unambiguously a scanner.

### No reverse proxy in front of uvicorn

The app is deployed as bare `uvicorn`, internet-facing, with no nginx/Caddy/
Traefik/WAF layer in front of it. All scanner/bot defense (rate limiting,
honeypots, probe detection, security headers) lives in `security.py` and
runs in-process.

**Why:** a single-process deployment doesn't need a proxy to terminate TLS
(uvicorn does that natively) or to load-balance, and the app-level defenses
already cover the traffic an internet-facing API actually receives —
adding a proxy now would be a second thing to operate and keep in sync with
no corresponding gap it closes. `TRUST_PROXY_HEADERS` stays `false`
precisely because there's nothing in front to set `X-Forwarded-For`
correctly (see `security.py`).

**Revisit when:** scaling to multiple worker processes (the in-memory
rate-limit counters need Redis or similar at that point regardless — see
the anti-abuse caveat above) or when TLS termination/load-balancing
requirements outgrow what uvicorn does alone. Either is a natural point to
add a proxy layer, not before.

### `ENABLE_DOCS` defaults to `false`

`/docs` and `/openapi.json` are FastAPI's built-in interactive API
explorer — extremely convenient in development, but they hand a scanner a
complete map of every endpoint and parameter for free.

**Why default off:** the cost of an internet-facing deployment leaking its
full API surface outweighs the convenience; anyone who needs it can flip it
on locally or point at `/docs` in a non-public environment.

## External integrations

### TMDB/Open Library responses cached in memory (30 min; covers 24h)

Read-only catalog responses are cached process-locally with a bounded
entry count (`CACHE_MAX_ENTRIES`) and evict-oldest-on-full behavior, not a
proper LRU.

**Why:** TMDB and Open Library both have free-tier rate limits, and search/
trending results don't change meaningfully minute-to-minute. A 30-minute TTL
cuts upstream call volume dramatically for near-zero staleness cost; covers
get a longer TTL (24h) since cover art essentially never changes.

### TMDB payloads persist for tracked titles (write-through, offline fallback)

Raw TMDB details/season/credits responses for titles that exist in the
`titles` table are stored in `tmdb_cache` (JSONB, keyed by title + kind +
season). Copies younger than `site_settings.tmdb_db_cache_hours` (seeded from
`TMDB_DB_CACHE_HOURS`, default 24, editable from `{ADMIN_PATH}/settings`) are
served without contacting TMDB; older ones are refreshed on access, and the stale
copy is served only when TMDB is unreachable. Explore browsing (search/
trending/popular, or details of untracked titles) is never persisted —
memory cache only — so the table is bounded by the titles table. Details
payloads also sync typed columns on `titles` (overview, tagline,
show_status, next_episode_air_date, total_seasons, genres); the notifier's
existing per-show poll refreshes all of this as a side effect, and a
library add triggers a best-effort sync.

**Why:** detail pages previously went blank whenever the server had no
route to TMDB (LAN-only deployments, outages) and every restart started
cold. Persisting raw payloads (not mapped responses) keeps one mapping
code path, and gating on "somebody tracks it" keeps growth bounded.
Vote averages are deliberately *not* trusted from old copies of typed
data — they change constantly and are read from the payload like
everything else, stale only during outages.

### Ended shows are not polled by the notifier

`titles.show_status` in ("Ended", "Canceled") excludes a show from the
periodic new-episode check. A detail-page visit still refreshes the
status, so a revived show recovers on its own.

**Why:** finished shows can never produce a notification; polling them
wastes the TMDB budget as libraries grow. The self-healing path via
detail views makes the rare revival case acceptable.

### `/upcoming` reads pre-synced Title columns, never fetches TMDB live

`GET /upcoming` used to call TMDB once per tracked title on every
request (parallelized across a thread pool). For a large library that
took over a minute and could still time out. It now reads
`Title.next_episode_air_date`/`next_episode_season`/`next_episode_number`/
`next_episode_name` (TV) and `Title.release_date` (film) directly off the
already-joined row — no network call on the request path at all.

Those columns are kept fresh by two periodic pollers in `notifier.py`:
the existing new-episode checker for TV shows, and a new
`check_upcoming_films` that refreshes `want_to_watch` films with an
unreleased (or unknown) `release_date`, stopping once a film's release
date is in the past — mirroring [Ended shows are not polled by the
notifier](#ended-shows-are-not-polled-by-the-notifier). `refresh_title_details`
on add/detail-visit covers the gap between a title being tracked and the
next poller run.

**Why:** the periodic pollers already exist for the notifier; letting
`/upcoming` read their output instead of re-fetching TMDB moves the cost
off the request path entirely, at the trade-off that a just-added title's
upcoming entry can lag by up to one poll interval (per-task, admin-configurable
from `<ADMIN_PATH>/periodic-tasks`; 6h by default) before it first appears.

### `/upcoming/history` backfills a per-episode table lazily, on request

Past releases (aired episodes, released films) needed real per-episode air
dates, which `Title.next_episode_*` can't provide — it holds only the single
next unaired episode, overwritten once it airs. A new `episodes` table
(title_id, season, episode_number, name, air_date — one row per TMDB-known
episode, shared across every user tracking the show, same lifecycle as
`titles`) fills that gap.

Rows are backfilled the first time `/upcoming/history` needs a show's
episodes (`sync_show_episodes`), one TMDB season call per season, through
the same persistent `tmdb_cache` path `season_tmdb()` uses. A season whose
last known episode already aired in the past is skipped on every later
call without contacting TMDB — only new, unannounced, or still-airing
seasons get refetched — so a show's history costs a burst of TMDB calls
once and indexed DB reads after that. Films need no equivalent: their
single `release_date` is already a real past-or-future fact once synced,
`/upcoming/history` just stopped excluding it once it's in the past.

**Why:** a full periodic per-episode sync job (mirroring the notifier's
show poller) would front-load TMDB cost across every tracked show whether
or not the user ever scrolls back to see it. Lazy sync on first access pays
that cost only for shows someone actually scrolls into, at the price of the
first `/upcoming/history` call for a show being slower than later ones —
the same trade-off `/upcoming` itself already accepted for cold titles
(see above) and the same TMDB-cache path every other detail fetch uses.

### External images live in the content-addressed store

TMDB posters/stills and Open Library covers fetched through the proxies
are stored as blake3-named files in the same store as user avatars, with
the upstream identity mapped in `external_images` (source + key →
images row). Each image is fetched from upstream at most once; identical
bytes are stored once. The old loose per-proxy cache directories
(`tmdb_cache/`, `book_covers/`) are gone.

**Why:** one storage system instead of three, DB-visible sizes/dedup, and
the immutable upstream paths make "cache forever, never revalidate" safe.

### TVDB is a fallback, not the primary lookup

TV Time imports match shows to TMDB via TVDB id first (TMDB's `/find`
crosswalk); only when that misses — common even for well-known shows — and
`TVDB_API_KEY` is configured does the importer call TheTVDB directly.

**Why:** TMDB is already required for the rest of the app, so using it as
the primary match keeps the import path dependency-free by default; TVDB is
an optional improvement for the (frequent enough to matter) crosswalk gaps,
not a hard requirement.

## Premium accounts

### Premium is a timestamp (`users.premium_until`), not a boolean

An account is premium while `premium_until` is in the future. Admin grants
extend from `max(now, premium_until)`; revoking nulls it. There is no
payment integration yet — the admin panel is the only writer.

**Why:** paid access lapses, renews and gets comped; one timestamp models
all of that with zero state machine, and a future payment provider becomes
"another thing that extends the same field" instead of a schema change.

### One derived badge, never a stored list

`verified` is a separate admin-granted flag (requested in-app via
`verification_requested`, granted/revoked only by the admin), and the badge
shown next to a username is *derived* per response: verified-and-premium →
`verified`, else premium → `premium`, else none.

**Why:** the product rule is "verified replaces premium, users never
accumulate badges" — deriving the badge makes that rule impossible to
violate, and lapsed premium automatically hides the verified badge too
(verification is a premium perk, not a lifetime grant).

### Style colors come from a server palette; lapse hides, never deletes

`ring_color`/`name_color` must be members of `premium.PALETTE` (422
otherwise). Public payloads (comments, profiles, feed) carry a `flair`
block — badge + colors — that is blanked while premium is inactive;
`/auth/me` alone returns the stored values so the style picker can show
the saved choice. The same keep-but-don't-serve rule applies to custom
posters.

**Why:** free-form hex invites unreadable-on-one-theme choices and
support burden; a curated palette is validated once server-side and every
client renders it consistently. Keeping (not deleting) customizations on
lapse means resubscribing restores everything instantly — the gentle
behavior users expect from subscriptions.

### Custom posters are per-entry image-store rows, never Title edits

A premium user's poster override lives on their `library_entries` row
(`custom_poster_image_id` → `images`). Both sources converge on the same
stored form: uploads and picked TMDB alternates are downloaded/decoded
server-side, normalized to bounded JPEG, and deduplicated in the
content-addressed store. `poster_url` serves the override only while the
owner is premium; clearing works without premium and GCs the image.

**Why:** `titles` is shared truth for every user — a personal reskin must
not touch it. Storing the TMDB choice as bytes (not a URL) gives one code
path, offline safety and dedup for free; the store's GC counts all six
reference sources (avatars, profile backgrounds, custom posters, custom
backdrops, episode stills, external images) in `image_service.py`
precisely because they all share the same `images` table and file store.

The same per-entry / never-Title rule and the same image-store path apply
to custom backdrops (`custom_backdrop_image_id` → `images`, landscape
16:9 JPEG, `PUT /media/{id}/backdrop`) and per-episode custom stills
(`episode_custom_stills.still_image_id` → `images`,
`PUT /media/{id}/episodes/{season}/{episode}/still`). All three
override types are independent: a user can mix a custom poster and a
default backdrop, or vice versa, and clearing any one of them GCs only
its own image file.

## API design

### CORS restricted to browser origins; the app itself is unaffected

`CORS_ORIGINS` only needs to list origins of browser-based clients (a
hypothetical web admin, a future web build). The Flet desktop/mobile app
is not a browser and does not send preflight requests, so it's never
blocked by this setting regardless of what's configured.

**Why documented here:** this is a common point of confusion — adding a
new client is often assumed to require a CORS change when it doesn't,
unless that client happens to run inside a browser.

### Referrer-Policy: `same-origin` on the admin panel, `no-referrer` elsewhere

The JSON API sends `Referrer-Policy: no-referrer`, but pages under
`ADMIN_PATH` send `same-origin` instead.

**Why:** per the Fetch spec, the `Origin` header on non-GET non-CORS
requests follows the page's referrer policy — under `no-referrer`,
browsers send `Origin: null` even on same-origin form POSTs. The
`OriginCheckMiddleware` (CSRF defense-in-depth) rightly rejects `null`
(it's what sandboxed attacker iframes send), so a blanket `no-referrer`
made every POST button in the admin panel answer 403 "Origin not
allowed". `same-origin` still keeps the referrer from leaking off-site
while letting the panel's own forms carry a real `Origin`.

### `GET /` exposes `app.version` unauthenticated, no admin role for it

`{"status": "ok", "message": "Connection to Renar OK", "version":
app.version}` is served with no auth, doubling as both the reachability
check (e.g. a phone confirming a LAN server address) and the version
source the frontend's Profile → About screen reads.

**Why:** a version number isn't sensitive, so gating it behind a new
per-user admin role on `User` would be schema/auth churn for no security
benefit — the existing HTTP-Basic `/admin` panel already covers real
admin needs and isn't tied to user accounts at all.

## Dev server

### Nothing may depend on the launch directory

`.env` lookup, `MEDIA_DIR`, and uvicorn's `reload_dirs` are all anchored
to the repo root (derived from `__file__`), never to the CWD. A relative
`MEDIA_DIR` in `.env` means "relative to the repo root".

**Why:** each of these silently degraded when `be` was launched from
another directory — hot-reload watched a nonexistent `src`, settings fell
back to defaults, media landed in a stray folder. None of them errored;
they just behaved differently depending on where the command was typed.

### Startup port probe + orphan watchdog (`_devserver.py`)

`be` refuses to start when something already listens on the port
(probing with `SO_EXCLUSIVEADDRUSE` on Windows), and the reload worker
exits when its reloader parent dies.

**Why:** uvicorn binds with `SO_REUSEADDR`, which on Windows lets a
second server bind the same port without an error — and a reload worker
whose parent was force-killed survives as exactly such a squatter. An
orphaned worker once answered every request on :8000 with day-old code
through any number of "restarts"; the two guards make that impossible
from both ends (a zombie can't be joined by a new server, and workers
can't outlive their reloader).

---

## Package structure (Common Closure Principle)

### Splitting `routers/admin.py` into `routers/admin/`

The original `routers/admin.py` was a 126 KB, 3 039-line god-file. It was
split into a package with domain-cohesive submodules:

| submodule | responsibility |
|---|---|
| `_html.py` | CSS constants, chart helpers, shared HTML utilities |
| `dashboard.py` | landing page (service-tile grid) |
| `users.py` | user list/detail/library + all user-action POSTs |
| `analytics.py` | site-wide usage stats and per-endpoint caller breakdown |
| `moderation.py` | comment review/deletion and banned-IP management |
| `settings.py` | site settings read/write |
| `invites.py` | invite-code generation and lifecycle |

`__init__.py` aggregates the six sub-routers under `APIRouter(prefix=_P)`
and is the sole public surface; `main.py` still calls
`app.include_router(admin.router)` unchanged.

**CCP rationale:** each submodule corresponds to a feature that changes
independently. Editing invite logic never touches the chart helpers; adding
a new moderation action never touches settings. Intra-feature helpers
(render functions, CSS) co-locate with the routes that use them.

### Grouping flat root-level files into subpackages

The 22 peer files at `src/renar_backend/` were regrouped into five
domain subpackages. Files at the root that are cross-cutting
(`models.py`, `schemas.py`, `config.py`, `database.py`, `site_settings.py`,
`db_triggers.py`, `constants.py`) stay at root level.

| subpackage | moved files | closed over |
|---|---|---|
| `media/` | `storage.py`, `http_cache.py`, `image_service.py`, `image_cache.py`, `image_utils.py` | content-addressed store + in-memory TTL cache |
| `tmdb/` | `tmdb_http.py`, `tmdb_store.py` | TMDB HTTP client + persistent payload cache |
| `users/` | `auth.py`, `security.py`, `premium.py`, `usage.py`, `accounts.py` | auth, middleware, premium rules, account lifecycle |
| `social/` | `comment_threads.py`, `notifier.py` | comment tree traversal + background episode checker |
| `catalog/` | `titles.py` | global Title resolution and genre management |

**CCP rationale:** files within each group change together — a change to
the image store pipeline touches `storage`, `image_service` and
`image_cache` but never `tmdb_store` or `auth`. Grouping by what-changes-
together keeps diffs local to one package.
