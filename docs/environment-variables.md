[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/09 08:05:52.275749 )
[//]: # (+ Revised: 	2026/07/09 08:05:52.275749 )
[//]: # ( ---------------------------------------------------------------------- )

# Environment variables

All settings live in `.env` (copy `.env.example` to start) and are read by
`src/xoutaim_backend/config.py`. Every variable has a safe default baked into
that file, so `.env` only needs to override what you care about.

## Core

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | dev placeholder | Signs login tokens (JWT). Must be a long random value in any environment other than local dev — the app logs a warning at startup if you leave the default in place, since tokens signed with a known key can be forged. |
| `DATABASE_URL` | `sqlite:///./xoutaim.db` | SQLAlchemy connection string. Swap for a Postgres URL (`postgresql://...`) for a real deployment. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | How long a login session stays valid before the client must log in again. |
| `CORS_ORIGINS` | `["http://localhost:8550", "http://127.0.0.1:8550"]` | Browser origins allowed to call the API (JSON list). Add your deployed frontend's URL here; the mobile/desktop app isn't a browser so it isn't affected by CORS. |

## External metadata sources

| Variable | Default | What it does |
|---|---|---|
| `TMDB_API_KEY` | empty | Key/token for [TheMovieDB](https://www.themoviedb.org/settings/api) — powers search, trending, posters and episode data for films/TV. Free to obtain; v3 key or v4 read token both work. Without it, `/tmdb/*` endpoints don't work. |
| `TVDB_API_KEY` | empty | Optional. Used as a fallback lookup when matching shows during a TV Time import. |
| `EPISODE_CHECK_MINUTES` | `360` (6h) | How often a background task polls TMDB for new episodes of tracked shows and creates notifications. |

## Storage

| Variable | Default | What it does |
|---|---|---|
| `MEDIA_DIR` | `./media` | Root folder for the content-addressed file store (avatars, cached posters/covers). |

## Admin panel

| Variable | Default | What it does |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | empty | HTTP Basic credentials for the admin panel. The panel returns 503 until **both** are set — there's no way to accidentally expose it with a blank password. |
| `ADMIN_PATH` | `/admin` | URL the admin panel is served at. Renaming it to something unguessable (e.g. `/nimda`, `/panel-x7k2`) is the main defense for this endpoint — see below, the *default* `/admin` path then automatically becomes a honeypot that permabans anyone who requests it. |

## Anti-abuse

See [anti-abuse.md](anti-abuse.md) for the full explanation of *why* these
values are what they are. Quick reference:

| Variable | Default | What it does |
|---|---|---|
| `ABUSE_GUARD_ENABLED` | `true` | Master switch for all rate limiting/banning. Tests turn it off since test traffic all comes from one IP. |
| `ENABLE_DOCS` | `false` | Serves `/docs` and `/openapi.json` when `true`. Leave off in any internet-facing deployment — it hands a full API map to scanners. |
| `REGISTRATION_OPEN` | `true` | Set `false` to stop new signups without touching anything else. |
| `TRUST_PROXY_HEADERS` | `false` | Set `true` **only** when running behind a reverse proxy/CDN (nginx, Caddy, Cloudflare) — it makes the app trust `X-Forwarded-For` for the real client IP. Leave `false` otherwise; that header is client-controlled and trusting it without a proxy lets anyone spoof their IP to dodge rate limits. |
| `EXEMPT_IPS` | `["127.0.0.1", "::1"]` | IPs (JSON list) that skip rate limiting/banning entirely — for monitoring or local tooling. |
| `RATE_LIMIT_PER_MINUTE` | `600` | Soft per-IP ceiling. Over it: `429` + `Retry-After`, never a ban. |
| `FLOOD_BAN_PER_MINUTE` | `2000` | Hard ceiling far above normal traffic. Over it: temporary ban. |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `30` | Requests per IP per minute to `/auth/login` and `/auth/register` (throttle only). |
| `REGISTER_PER_HOUR_PER_IP` | `20` | New accounts per IP per hour (throttle only). |
| `LOGIN_BACKOFF_THRESHOLD` | `5` | Failed logins for one (account, IP) pair before that pair gets a cooldown. |
| `LOGIN_BACKOFF_ACCOUNT_THRESHOLD` | `30` | Failed logins for one account across *all* IPs before the account itself gets a cooldown (blunts distributed credential stuffing). |
| `LOGIN_BACKOFF_MINUTES` | `15` | Length of the login cooldown. |
| `PROBE_BAN_THRESHOLD` | `12` | Requests to paths that match no route at all, within the window below, before a temporary ban. |
| `PROBE_WINDOW_MINUTES` | `10` | Rolling window for probe counting. |
| `BAN_MINUTES` | `60` | First-offense temporary ban length; doubles for each repeat offense within 24h of the last one, capped at 24h. |
| `STRIKE_BAN_THRESHOLD` | `5` | Persisted offenses (see the `strikes` table) an IP can accumulate before a temporary ban escalates into a permanent one. Streak resets after 24h with no new offense; rows untouched for 30 days are pruned. |

## Notes

- JSON-list variables (`CORS_ORIGINS`, `EXEMPT_IPS`) must be valid JSON in the
  `.env` file, e.g. `CORS_ORIGINS=["https://app.example.com"]`.
- Lines starting with `#` in `.env` are comments and are ignored.
- Changing a value requires restarting the process — `pydantic-settings`
  reads `.env` once at startup.
