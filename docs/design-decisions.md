[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:10:01.809974 )
[//]: # (+ Revised: 	2026/07/09 09:45:17.199771 )
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

### Content-addressed image store (`storage.py`)

Uploaded/cached images (avatars, cached posters, book covers) are stored by
the BLAKE3 hash of their bytes, in a git-style two-level directory fan-out
(`media/images/<hash[:2]>/<hash[2:4]>/<hash>.jpg`).

**Why:** identical content (the same poster fetched for two different users,
or a re-uploaded avatar) is stored exactly once. The two-level fan-out keeps
any single directory from accumulating thousands of entries, which degrades
listing performance on most filesystems.

### SQLite by default, Postgres via `DATABASE_URL`; schema owned by Alembic

The app never creates tables itself — every schema change is an Alembic
migration, run in batch mode so `ALTER` works on SQLite too (SQLite can't
alter columns in place; batch mode rebuilds the table).

**Why:** SQLite needs zero setup for local dev and small deployments;
Postgres is a one-variable swap when it's time to scale. Alembic-owned
schema means `git log` on `alembic/versions/` is a complete, reviewable
history of every structural change — there's no implicit "the app just
fixes it up on startup" behavior to reason about.

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

### Admin panel: server-rendered HTML behind HTTP Basic, not a JSON API + SPA

`/admin` renders HTML directly from FastAPI rather than exposing admin data
as JSON for a separate frontend to consume.

**Why:** it avoids building and shipping a second frontend for a feature
only the operator uses, and keeps the public JSON API free of
admin-only routes that would otherwise need their own auth scheme layered
onto the JWT system. The tradeoff (no rich client-side interactivity) is
acceptable for an infrequently used internal tool.

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

### TVDB is a fallback, not the primary lookup

TV Time imports match shows to TMDB via TVDB id first (TMDB's `/find`
crosswalk); only when that misses — common even for well-known shows — and
`TVDB_API_KEY` is configured does the importer call TheTVDB directly.

**Why:** TMDB is already required for the rest of the app, so using it as
the primary match keeps the import path dependency-free by default; TVDB is
an optional improvement for the (frequent enough to matter) crosswalk gaps,
not a hard requirement.

## API design

### CORS restricted to browser origins; the app itself is unaffected

`CORS_ORIGINS` only needs to list origins of browser-based clients (a
hypothetical web admin, a future web build). The Flet desktop/mobile app
is not a browser and does not send preflight requests, so it's never
blocked by this setting regardless of what's configured.

**Why documented here:** this is a common point of confusion — adding a
new client is often assumed to require a CORS change when it doesn't,
unless that client happens to run inside a browser.
