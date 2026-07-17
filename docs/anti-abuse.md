[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:52.135465 )
[//]: # (+ Revised: 	2026/07/17 09:40:41.412525 )
[//]: # ( ---------------------------------------------------------------------- )

# Anti-abuse system

Implemented in `src/xoutaim_backend/security.py`, wired in as middleware in
`main.py`. This exists because the API is exposed to the open internet and
attracts constant scanner/bot traffic, while still needing to never punish a
real user. Everything below is tuned around one rule: **many legitimate users
can share one IP** (an office, a mobile carrier's CGNAT pool), so the default
response to too much traffic is always a throttle, not a ban. Bans are
reserved for behavior no legitimate client can produce by accident.

State is all in-memory (a single dict/deque per tracker), which matches a
single-process deployment — restarting clears temporary bans, and a scanner
re-earns them within seconds. Permanent bans are the exception: they're
persisted in the `banned_ips` table so they survive a restart. If this ever
scales to multiple workers/processes, this state needs to move to Redis or
similar so all workers see the same counters.

## The five layers

### 1. Honeypot paths — instant, permanent ban

`HONEYPOT_PATHS` / `HONEYPOT_PREFIXES` in `security.py` list URLs no real
client of this API would ever request: `/.env`, `/wp-login.php`,
`/.aws/credentials`, `/phpmyadmin`, `/.git/config`, etc. Requesting one of
these is a scanner fingerprinting the server, full stop — zero false-positive
risk. One hit permabans the IP (`permaban()`), persisted to the `banned_ips`
table, and returns a plain `404` so the scanner doesn't learn it hit a trap.
Review or lift these bans at `<ADMIN_PATH>/bans`.

`robots.txt` advertises `Disallow: /internal/` specifically as bait: well-
behaved crawlers respect it and move on, while scanners that scrape
`robots.txt` looking for "hidden" paths walk straight into the honeypot.

If you rename the admin panel via `ADMIN_PATH` (recommended), the *default*
`/admin` location automatically becomes a honeypot too, since nothing
legitimate should ever hit it once it's been moved.

### 2. Probe detection — repeated 404s on nonexistent routes

Scanners map an API by requesting many different paths and seeing what
sticks. `_matches_no_route()` checks whether a request's path matches *no
registered route at all* — a real client hitting a 404 for a deleted item or
a stale link, or a 405 on a route that exists, never counts. Only genuinely
unknown paths accumulate in `probe_hits`. Hit `PROBE_BAN_THRESHOLD` (default
12) unknown paths within `PROBE_WINDOW_MINUTES` (default 10) and the IP gets
a temporary ban.

Requests carrying a valid signed session token are exempt from this counter
entirely — the reasoning is that a real, identifiable user (e.g. an app
version calling an endpoint that's since been removed) must never get banned
for it, since forging that token is infeasible without `SECRET_KEY`.

### 3. Rate limiting — throttle first, ban only for floods

Every counted request (i.e. not `/health` or `/robots.txt`, which must never
eat into a client's budget) increments a per-IP counter with a 1-minute
window:

- Over `RATE_LIMIT_PER_MINUTE` (default 600): `429` + `Retry-After`. This is
  the normal response to "busy office/app user", not an attack signal.
- Over `FLOOD_BAN_PER_MINUTE` (default 2000): an unambiguous flood — nothing
  legitimate sends 2000 req/min from one IP — earns a temporary ban.

`/auth/login` and `/auth/register` get an additional, tighter per-IP budget
(`AUTH_RATE_LIMIT_PER_MINUTE`, default 30/min) since each request there is a
credential guess or account creation. Registration also has an hourly cap
per IP (`REGISTER_PER_HOUR_PER_IP`, default 20/hour) to blunt bulk
signups.

Temporary bans escalate: the duration is `BAN_MINUTES * 2^(offense count - 1)`,
capped at 24 hours, and the offense count resets if the IP has behaved for
24 hours since its last one. So a first offense is a short ban; a repeat
scanner gets progressively longer bans automatically.

### 4. Per-account login backoff

This one lives in `check_login_allowed()` / `note_login_failure()`, called
directly from the `/auth/login` endpoint rather than the middleware, because
only the endpoint knows which *account* was targeted and whether the attempt
succeeded. Two independent trackers:

- **Per (account, IP)**: `LOGIN_BACKOFF_THRESHOLD` (default 5) failures locks
  that specific account+IP combination out for `LOGIN_BACKOFF_MINUTES`
  (default 15) — stops one source from brute-forcing one account.
- **Per account, across all IPs**: `LOGIN_BACKOFF_ACCOUNT_THRESHOLD` (default
  30) failures locks the account out regardless of source IP — blunts
  distributed credential stuffing (many IPs, one target account) without
  letting a griefer lock a victim out by spraying a handful of failures from
  one IP.

A successful login clears both trackers for that account immediately.

### 5. Repeat-offender strikes — persisted escalation to a permaban

Every temporary ban from layers 2–3 (probe detection, flood limiting) also
records a strike in the `strikes` table: one row per IP, upserted, so the
table is bounded by distinct offenders rather than request volume. A day
with no new offense resets that IP's streak back to a count of 1.

Because strikes are persisted (not in-memory like the counters above), an
offender who waits out a restart doesn't get a clean slate — `count` and
the active `banned_until` are reloaded from the DB on startup. Once `count`
reaches `STRIKE_BAN_THRESHOLD` (default 5), the next offense converts the
temporary ban into a permanent one (same mechanism as the honeypot bans in
layer 1). Rows untouched for 30 days are pruned automatically so the table
doesn't grow unbounded from one-off offenders. Manage strikes/permabans
from `<ADMIN_PATH>/bans`.

## Supporting middleware (not rate limiting, but same file's territory)

- **`SecurityHeadersMiddleware`** — sets baseline hardening headers
  (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  HSTS) on every response, plus a `Content-Security-Policy`: the strict
  `default-src 'none'` for the JSON API, or a relaxed self+inline-script/style
  policy scoped to `ADMIN_PATH` since that panel is server-rendered HTML.
- **`OriginCheckMiddleware`** — rejects cross-site browser requests (mismatched
  `Origin` header) on unsafe methods (`POST`/`PUT`/`PATCH`/`DELETE`). Auth here
  is a bearer token rather than a cookie, so classic CSRF doesn't apply
  directly — this is defense-in-depth for a browser client that sends the
  token anyway. Non-browser clients (the app, curl, server-to-server calls)
  don't send `Origin` at all and are unaffected.

## Sharing bans with the frontend

The API isn't the only internet-facing surface — `xoutaim-frontend`'s web
server (`uv run web`, a Flet/FastAPI app on its own port) is exposed
directly too, and gets scanned independently of the API. It runs its own
scaled-down copy of this guard (`anti_abuse.py` in that repo: honeypots,
flood/probe temp bans — no login-specific logic, since it's a UI server with
no auth endpoints of its own).

Rather than give the frontend its own database, it shares this server's
`banned_ips` *and* `strikes` tables over three machine-to-machine endpoints
in `routers/svc.py` — the frontend has no persistence of its own at all:

- `GET /svc/bans` — returns both permabanned IPs and currently-active temp
  bans (`load_active_temp_bans()`). The frontend preloads this on startup so
  a restart doesn't grant amnesty to an IP either surface already banned,
  temporarily or permanently. Past startup, it also re-pulls this on a long
  interval (default 60 minutes — `XOUTAIM_ABUSE_SYNC_INTERVAL_SECONDS` on
  the frontend) to pick up a ban recorded only on this server (e.g. its own
  honeypot/admin bait) that the frontend was never told about directly. Only
  the permaban list is merged from that periodic refresh — temp bans are
  intentionally left out of it (see below) — and it's frontend-initiated,
  so this server never needs to know the frontend exists.
- `POST /svc/bans` — the frontend calls this the moment its own guard decides
  to permaban an IP (honeypot hit — zero false-positive risk, so this always
  goes straight to a permaban), so that IP is blocked here too if it ever
  targets the API directly.
- `POST /svc/strikes` — the frontend calls this for everything else (floods),
  going through the exact same `strike_and_maybe_ban()` escalation logic used
  for this server's own offenders: first offense is a short temp ban, repeat
  offenses double it (capped at 24h), and hitting `STRIKE_BAN_THRESHOLD`
  converts it to a permaban — automatically, via the same `strikes` row an
  API-side offense against the same IP would use.

Temp bans made on one surface but not the other are deliberately *not*
chased down by the periodic refresh: they already expire on their own
(60 min default, doubling per repeat offense), so a delayed sync could
easily arrive after the ban's already lapsed — not worth the extra
complexity. Permabans have no such expiry, so lag there costs nothing;
that's why only they're worth syncing periodically.

Both `/svc/bans` and `/svc/strikes` require the `X-Internal-Secret` header to
match `INTERNAL_SERVICE_SECRET` exactly (constant-time compare); a
missing/wrong secret gets a plain `404`, not `401`/`403`, so an
unauthenticated prober learns nothing. Deliberately **not** under
`/internal/` — that prefix is honeypot bait (see `HONEYPOT_PREFIXES`) and
would permaban the frontend itself the moment `INTERNAL_SERVICE_SECRET` was
left unset.

If the frontend can't reach these endpoints (secret unset, or the backend is
down), its guard falls back to a local, in-memory-only ban so the defense
still works — it just isn't persisted or shared until connectivity is back.

The frontend's temporary bans/rate-limit counters stay in-memory only, same
as this server's: a scanner just re-earns them within seconds of a restart.

## Operating it

- `ABUSE_GUARD_ENABLED=false` disables everything in this file except the
  security headers and origin check — used in tests, where all traffic
  legitimately comes from one IP.
- `TRUST_PROXY_HEADERS` must stay `false` unless there's an actual reverse
  proxy/CDN in front of the app. `client_ip()` reads the rightmost entry of
  `X-Forwarded-For` — the hop appended by *your* proxy — when trusted;
  without a proxy that header is entirely client-supplied, so trusting it
  would let anyone spoof their apparent IP to dodge every limit above, or
  get an innocent IP (the proxy's own) banned.
- All tunables are environment variables — see
  [environment-variables.md](environment-variables.md) for the full list of
  defaults.

## DB-backed runtime settings

The twelve anti-abuse tunables and the two registration flags (`registration_open`,
`invite_only`) are stored in a `site_settings` singleton row (id always 1,
same pattern as `app_counters`) so they can be changed from the admin panel at
`<ADMIN_PATH>/settings` without a server restart.

`src/xoutaim_backend/site_settings.py` provides:

- `get_site_settings(db)` — reads or creates the singleton; on first call it
  seeds the row from the corresponding `config.py` / `.env` defaults so existing
  deployments keep their tuned values.
- `current()` — 5-second TTL in-process cache used by `AbuseGuardMiddleware`
  (which runs on every request) to avoid a DB hit per request.  The admin POST
  handler calls `invalidate()` after committing so the new values propagate
  within the TTL, not just after it.
- Defensive fallback: if the `site_settings` table doesn't exist (migration not
  run, fresh checkout) `current()` falls back to the config defaults and retries
  on the next call rather than crashing every request.

## Invite-only registration

When `site_settings.invite_only` is `true`, every `POST /auth/register` request
must include a valid `invite_code` field.  A code is valid when:

- it exists in the `invite_codes` table,
- it is not revoked (`revoked = false`),
- `uses < max_uses`, and
- `expires_at` is `NULL` or in the future.

On a successful registration the code's `uses` counter is incremented in the
**same transaction** as the new user row, so a crash or race can never consume a
code without creating the user, or create a user without consuming the code.

Codes are generated from the admin panel at `<ADMIN_PATH>/invites` (max uses and
optional expiry configurable per code).  The revoke button on that page marks a
code as `revoked = true`; already-used slots are not refunded.

`invite_only` and `registration_open` are independent: if `registration_open` is
`false`, registration is closed entirely regardless of any invite code.
