[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:52.275749 )
[//]: # (+ Revised: 	2026/11/10 13:53:26.153709 )
[//]: # ( ---------------------------------------------------------------------- )

# Environment variables

All settings live in `.env` (copy `.env.example` to start) and are read by
`src/renar_backend/config.py`. Most variables have a safe default baked
into that file, so `.env` only needs to override what you care about;
`DATABASE_URL` is the exception and must always be set.

## Core

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | dev placeholder | Signs login tokens (JWT). Must be a long random value in any environment other than local dev — the app logs a warning at startup if you leave the default in place, since tokens signed with a known key can be forged. |
| `DATABASE_URL` | *(required)* | SQLAlchemy Postgres connection string, e.g. `postgresql+psycopg://user:password@host:5432/renar`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | How long a login session stays valid before the client must log in again. |
| `CORS_ORIGINS` | `["http://localhost:8550", "http://127.0.0.1:8550"]` | Browser origins allowed to call the API (JSON list). Add your deployed frontend's URL here; the mobile/desktop app isn't a browser so it isn't affected by CORS. |

## External metadata sources

| Variable | Default | What it does |
|---|---|---|
| `TMDB_API_KEY` | empty | Key/token for [TheMovieDB](https://www.themoviedb.org/settings/api) — powers search, trending, posters and episode data for films/TV. Free to obtain; v3 key or v4 read token both work. Without it, `/tmdb/*` endpoints don't work. |
| `TVDB_API_KEY` | empty | Optional. Used as a fallback lookup when matching shows during a TV Time import. |

Background-task poll intervals (episode check, episode history sync, film
release check, TMDB metadata resync, strike cleanup) are no longer env vars —
each is independently enabled and scheduled from the admin panel's Periodic
Tasks page (`<ADMIN_PATH>/periodic-tasks`), stored in the database.

## Storage

| Variable | Default | What it does |
|---|---|---|
| `MEDIA_DIR` | `./media` | Root folder for the content-addressed file store (avatars, cached posters/covers). |

## CAPTCHA

| Variable | Default | What it does |
|---|---|---|
| `PROD_TURNSTILE_SITE_KEY` / `PROD_TURNSTILE_SECRET_KEY` | empty | [Cloudflare Turnstile](https://dash.cloudflare.com/?to=/:account/turnstile) keys, checked on `/auth/register`. Leaving both empty skips the check entirely (dev default). The on/off switch itself is `SiteSettings.turnstile_enabled` (admin panel, seeded from this same `TURNSTILE_*`-adjacent config), not an env var — disabling it falls back to IP rate-limiting only, no keys needed. **Stays in `.env`** (real secrets). |
| `DEV_TURNSTILE_SITE_KEY` / `DEV_TURNSTILE_SECRET_KEY` | empty | Second Turnstile widget, used instead of the `PROD_TURNSTILE_*` pair for any request whose `Host` header matches the admin panel's "Turnstile dev hostnames" field (`SiteSettings.turnstile_dev_hostnames`, Registration section — **seeded** from `TURNSTILE_DEV_HOSTNAMES` here, live value owned by the admin panel from first read onward, same as `exempt_ips`). Decided purely from the incoming request (`Settings.turnstile_site_key_for`/`turnstile_secret_key_for` in `config.py`) — no client-sent flag, nothing to remember to flip; a request to any other hostname always gets the prod pair. **Stays in `.env`**. |
| `TURNSTILE_DEV_HOSTNAMES` | `[]` | **Seed default only.** Live value in `site_settings.turnstile_dev_hostnames`, editable from `{ADMIN_PATH}/settings` (a tag-input, like Exempt IPs) — JSON list here, comma-separated there. Hostnames must exactly match the request's `Host` header, no scheme/port — e.g. `["api.dev.renar.app"]`. |

## Email

| Variable | Default | What it does |
|---|---|---|
| `BREVO_API_KEY` | empty | API key for [Brevo](https://www.brevo.com) transactional email, used to send registration/email-change confirmation codes. Empty means the code is logged to the server console instead of sent — safe to leave unset until a verified sending domain is ready. **Stays in `.env`** (a real secret, not runtime-tunable). |

Sender name/address, confirmation-code lifetime, the login grace period, and
the unconfirmed-account cleanup age are **seed defaults only** — see
[anti-abuse.md — DB-backed settings](anti-abuse.md#db-backed-runtime-settings)
for how that seeding works. All four live in `site_settings` from first boot
onward and are edited from `{ADMIN_PATH}/settings`, not `.env`.

## Admin panel

| Variable | Default | What it does |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | empty | Sign-in for the admin panel's login page (`<ADMIN_PATH>/login`), together with an authenticator code. The panel returns 503 until these **and** `ADMIN_TOTP_SECRET` are set — there's no way to accidentally expose it with a blank password. Changing either signs every admin session out. |
| `ADMIN_TOTP_SECRET` | empty | Base32 secret for the authenticator-app (TOTP) code the login page asks for. Required for the panel. Generate one with `uv run admin-totp` (prints the secret, a QR code to scan and the `.env` line). Validated at boot: a value that isn't base32 stops the server with `ADMIN_TOTP_SECRET is not valid base32`. Rotating it signs every admin session out. **Stays in `.env`**. |
| `ADMIN_API_TOKEN` | empty | Bearer token for the admin routes a script calls (the APK upload and delete renar-frontend's `uv run build apk --split --publish` uses), since a script can't type an authenticator code. Empty means no token is accepted. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. **Stays in `.env`**. |
| `ADMIN_PATH` | `/admin` | URL the admin panel is served at. Renaming it to something unguessable (e.g. `/nimda`, `/panel-x7k2`) is the main defense for this endpoint — see below, the *default* `/admin` path then automatically becomes a honeypot that permabans anyone who requests it. |
| `UPDATE_RELEASE_URL` | `https://api.github.com/repos/Ran-n/renar-backend/releases/latest` | "Latest release" JSON the admin panel's Server Update page reads when the server isn't a git checkout (a checkout follows `origin/master` instead) (GitHub's, or Forgejo/Codeberg's `/api/v1/repos/<owner>/<repo>/releases/latest`, same shape). The update installs that release's `renar_backend-<version>.tar.gz` asset after checking its `.tar.gz.b3` BLAKE3 sum. Point it at a fork's releases to follow that fork. |
| `INTERNAL_SERVICE_SECRET` | empty | Shared secret for `/svc/bans` (see [anti-abuse.md](anti-abuse.md#sharing-bans-with-the-frontend)), which lets the renar-frontend web server's own anti-abuse guard read and add to this server's `banned_ips` table. Empty means the endpoints stay 404 to everyone, same posture as an unset admin panel. Must match `RENAR_INTERNAL_SECRET` in the frontend's `.env`. |

## Anti-abuse

See [anti-abuse.md](anti-abuse.md) for the full explanation of *why* these
values are what they are.  Most of the tunables below **have moved to the
database** (see [anti-abuse.md — DB-backed settings](anti-abuse.md#db-backed-runtime-settings))
and are now controlled from the admin panel at `{ADMIN_PATH}/settings` without
a restart.  The `.env` values in this section are only used as **seed defaults**
when the `site_settings` row is first created (i.e. on a fresh deployment); from
that point on the database owns them.  Quick reference:

| Variable | Default | What it does |
|---|---|---|
| `ABUSE_GUARD_ENABLED` | `true` | Master switch for all rate limiting/banning. Tests turn it off since test traffic all comes from one IP. **Stays in `.env`** (infrastructure flag, not runtime-tunable). |
| `ENABLE_DOCS` | `false` | Serves `/docs` and `/openapi.json` when `true`. Leave off in any internet-facing deployment — it hands a full API map to scanners. **Stays in `.env`**. |
| `REGISTRATION_OPEN` | `true` | **Seed default only.** The live value is in `site_settings.registration_open`, editable from `{ADMIN_PATH}/settings`. |
| `TRUST_PROXY_HEADERS` | `false` | **Seed default only.** Live value in `site_settings`, editable from `{ADMIN_PATH}/settings`. Set `true` **only** when running behind a reverse proxy/CDN (nginx, Caddy, Cloudflare) — it makes the app trust `X-Forwarded-For` for the real client IP. Leave `false` otherwise; that header is client-controlled and trusting it without a proxy lets anyone spoof their IP to dodge rate limits — the same caution applies whether it's set here or flipped in the panel. |
| `EXEMPT_IPS` | `["127.0.0.1", "::1"]` | **Seed default only.** Live value in `site_settings`, editable from `{ADMIN_PATH}/settings` as a comma-separated list. IPs that skip rate limiting/banning entirely — for monitoring or local tooling only, never a shared/public IP. |
| `RATE_LIMIT_PER_MINUTE` | `600` | **Seed default only.** Live value in `site_settings`. |
| `FLOOD_BAN_PER_MINUTE` | `2000` | **Seed default only.** Live value in `site_settings`. |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `30` | **Seed default only.** Live value in `site_settings`. |
| `REGISTER_PER_HOUR_PER_IP` | `20` | **Seed default only.** Live value in `site_settings`. |
| `LOGIN_BACKOFF_THRESHOLD` | `5` | **Seed default only.** Live value in `site_settings`. |
| `LOGIN_BACKOFF_ACCOUNT_THRESHOLD` | `30` | **Seed default only.** Live value in `site_settings`. |
| `LOGIN_BACKOFF_MINUTES` | `15` | **Seed default only.** Live value in `site_settings`. |
| `PROBE_BAN_THRESHOLD` | `12` | **Seed default only.** Live value in `site_settings`. |
| `PROBE_WINDOW_MINUTES` | `10` | **Seed default only.** Live value in `site_settings`. |
| `BAN_MINUTES` | `60` | **Seed default only.** Live value in `site_settings`. |
| `STRIKE_BAN_THRESHOLD` | `5` | **Seed default only.** Live value in `site_settings`. |
| `TMDB_DB_CACHE_HOURS` | `24` | **Seed default only.** Live value in `site_settings.tmdb_db_cache_hours`, editable from `{ADMIN_PATH}/settings`. How long a persisted TMDB payload (details/season/credits of a tracked title, stored in the `tmdb_cache` table) is served without re-contacting TMDB. Older copies refresh on access and are served stale only while TMDB is unreachable. |

## Notes

- JSON-list variables (`CORS_ORIGINS`, `EXEMPT_IPS`) must be valid JSON in the
  `.env` file, e.g. `CORS_ORIGINS=["https://app.example.com"]`.
- Lines starting with `#` in `.env` are comments and are ignored.
- Changing a value requires restarting the process — `pydantic-settings`
  reads `.env` once at startup.
