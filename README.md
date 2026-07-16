[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/07 13:28:52.145659 )
[//]: # (+ Revised: 	2026/07/16 09:54:29.938960 )
[//]: # ( ---------------------------------------------------------------------- )

# Xoutaim Backend

FastAPI backend for Xoutaim — your personal media tracker (films, TV shows, books, YouTube videos and more).

> Books and YouTube are fully implemented here (endpoints, models, imports),
> but the current frontend hides their tabs/cards (scope narrowed to
> tv/movies for now) — see xoutaim-frontend's README.

## Setup (uses [uv](https://docs.astral.sh/uv/))

```powershell
uv sync
copy .env.example .env   # then edit SECRET_KEY
```

## Run

```powershell
uv run alembic upgrade head   # apply database migrations (first run and after every pull)
uv run uvicorn xoutaim_backend.main:app --reload
```

## HTTPS

Local development runs over plain HTTP (traffic never leaves the machine /
home network). For TLS, uvicorn supports it natively — no proxy needed:

```powershell
uv run uvicorn xoutaim_backend.main:app --ssl-keyfile key.pem --ssl-certfile cert.pem
```

A public deployment should get certificates from the platform or Let's Encrypt.

## Docs

See [docs/](docs/) for a full explanation of every `.env` setting, how the
anti-abuse (rate limiting / banning) system works, and the reasoning behind
the data model and other non-obvious architecture choices.

## Changing the schema

Edit `src/xoutaim_backend/models.py`, then:

```powershell
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/ before applying!
uv run alembic upgrade head
```

API docs: http://127.0.0.1:8000/docs

## Endpoints

- `POST /auth/register` — create account
- `POST /auth/login` — get JWT token (form fields: username, password; username also accepts email)
- `GET /auth/me` — current user; `DELETE /auth/me` — delete account (cleans up all data)
- `PATCH /auth/profile` — update username / email / language / avatar; also sets
  `show_original_titles`, home screen preferences (`home_hero_enabled`,
  `home_on_launch`, `home_progress_style`), and — with active premium —
  profile background image and UI theme (gruvbox is free; all other themes
  require a subscription); also sets `has_seen_welcome`
- `POST /auth/change_password` — change password
- `GET /media` — list your items (filters: `media_type`, `status_filter`,
  `search`, `favorites_only`; `limit`/`offset` for pagination; optional `lang`
  returns localized title display names from cached TMDB translations,
  warming missing translations in the background)
- `POST /media` — save a film / tv_show / book / youtube item
- `GET /media/{id}` / `PATCH /media/{id}` / `DELETE /media/{id}`
- `GET /media/ratings?tmdb_id=...|title=...` — community average rating for a title
- `POST /media/{id}/rewatch` — log a rewatch of a whole item or one episode
- `PUT /media/{id}/poster` / `DELETE /media/{id}/poster` — premium: set a custom
  poster (TMDB alternate or upload) on one owned entry, or clear it back to default
  (clearing needs no premium)
- `PUT /media/{id}/backdrop` / `DELETE /media/{id}/backdrop` — premium: same as
  above for the landscape backdrop/banner image; clearing needs no premium
- `PUT /media/{id}/episodes/{season}/{episode}/still` /
  `DELETE /media/{id}/episodes/{season}/{episode}/still` — premium: per-episode
  custom still override; same shape as the item-level poster/backdrop
- `GET /tmdb/search?query=...&media_type=film|tv_show` — TMDB proxy for auto-filling
  titles, years and posters (requires `TMDB_API_KEY` in `.env`; free key from
  https://www.themoviedb.org/settings/api — v3 key or v4 read token both work)
- `GET /tmdb/trending?media_type=...` / `GET /tmdb/popular?media_type=...` — Explore feeds
- `GET /tmdb/details?media_type=...&tmdb_id=...` — runtime, episode count, genres
- `GET /tmdb/season?tmdb_id=...&season_number=...` — episode list for a season
- `GET /tmdb/posters?media_type=...&tmdb_id=...` — official alternate posters
  (curated source for the premium poster picker grid)
- `GET /tmdb/credits?media_type=...&tmdb_id=...` — cast/crew for a title
- `GET /tmdb/image/{size}/{filename}` — TMDB poster proxy served from our origin
- `GET /books/search?query=...` — Open Library proxy for auto-filling title, author,
  year, page count and cover (free, no API key)
- `GET /books/trending` — Open Library daily trending feed
- `GET /books/cover/{cover_id}` — cached/redirect-safe cover image proxy
- `GET /stats` — watch time, films/episodes watched, shows completed, favorites, top genres
- `GET /stats/ranking/metrics` — premium: list of available leaderboard metrics
- `GET /stats/ranking?metric=...` — premium: percentile rank on one metric
  (defaults to the metric the user ranks best on)
- `GET/PUT/POST /media/{id}/episodes...` — per-episode watched/rating tracking
  (`PUT .../episodes/{season}/{episode}`, `POST .../episodes/bulk`); responses include
  overall grade, episode average and combined score
- `GET /users/search`, `GET /users/{id}[/followers|/following|/media]`,
  `POST/DELETE /users/{id}/follow`, `GET /feed` — social graph and activity feed
- `GET/POST /comments`, `DELETE /comments/{id}`, `POST/DELETE /comments/{id}/like`,
  `POST/DELETE /comments/{id}/report` — comments (global per title via TMDB id)
  with likes, nested replies and retractable reports; a reply's title/season/episode
  scope is resolved from its thread root, not stored per-reply
- `GET /premium/palette` — server-defined color options for the ring/name color pickers
- `PATCH /premium/style` — premium: set avatar ring color / username color
  (explicit null clears one)
- `POST/DELETE /premium/verification-request` — request or withdraw the verified-badge
  request (withdrawal needs no active premium; granting is admin-only, see below)
- `GET /notifications` (+ `/unread_count`, `POST /{id}/read`, `POST /read_all`,
  `DELETE /{id}`, `POST /check_now`) — new-episode notifications for tracked shows
- `GET /upcoming` (+ `/history`) — countdown feed: next episodes and film premieres
  for tracked titles, plus a history of past ones
- `GET /youtube/resolve?url=...` — title/channel/thumbnail for a YouTube URL (oEmbed, no key)
- `GET /youtube/search_channels`, `GET /youtube/trending_channels`,
  `GET /youtube/channel_videos`, `GET /youtube/video_info` — YouTube Data API proxy
  for Explore's YouTube feed (requires `YOUTUBE_API_KEY` in `.env`)
- `POST /import/tvtime` + `GET /import/tvtime/status` — import a TV Time GDPR export zip
  (runs in the background; the status endpoint reports progress)
- `GET /images/{hash}` — content-addressed stored files (avatars, profile
  backgrounds, custom posters, custom backdrops, episode stills)
- `GET/POST /svc/bans`, `POST /svc/strikes` — machine-to-machine, guarded by
  `INTERNAL_SERVICE_SECRET` (not the admin session): lets the frontend's own
  web-server anti-abuse guard share this server's persisted ban/strike state
  (see [docs/anti-abuse.md](docs/anti-abuse.md)); deliberately not under `/internal/`,
  which is honeypot bait
- `GET /admin` — HTML admin panel behind HTTP Basic; returns 503 until
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` are set in `.env`. Tiles:
  - **User manager** (`/users`) — per-user usage stats (logins, requests, last
    login/active), ban/unban, delete. Clicking a username opens a **detail page**
    (`/users/{id}`) with account actions (edit username/email, set a new password,
    ban, delete, grant/revoke premium days, verify/unverify —
    `POST /users/{id}/edit`, `/password`, `/premium`, `/premium/revoke`, `/verify`,
    `/unverify`), inline-SVG per-day charts
    (requests / connections / watches / comments / library-adds over 30 days, with
    hover tooltips showing each day's value), and library breakdowns by type and
    status. The requests-per-day chart links to a full per-endpoint breakdown
    (`/users/{id}/endpoints`); each library breakdown row drills into the titles
    behind it (`/users/{id}/library`); each endpoint into its site-wide callers.
  - **Usage & analytics** (`/usage`) — site-wide **requests-by-endpoint** graph
    (populated by `UsageTrackingMiddleware`, keyed by route template so cardinality
    is bounded), plus connections- and signups-per-day. Each endpoint drills into
    its callers (`/usage/endpoint?method=&path=`), which link back to user pages.
  - **Comment manager** (`/comments?user_id=...`) — full comment text with
    per-comment delete.
  - **Banned IPs** (`/bans`) — review and lift honeypot bans.

TMDB and Open Library responses are cached in memory for 30 minutes; book covers for 24 hours.

A background task checks every `EPISODE_CHECK_MINUTES` (default 360) whether any
tracked show aired a new episode in the last 7 days, and creates a notification
per user — skipping episodes the user already marked watched.

## Tests

```powershell
uv run pytest
```

The suite spins up the app against a throwaway schema on the local Postgres
server (no `.env` or API keys needed) and covers every endpoint's happy and
error paths.

## Notes

- Requires Postgres; set `DATABASE_URL` in `.env` (see `.env.example`).
- Schema is owned by Alembic (`alembic/versions/`); the app no longer creates tables itself.

## License

[PayBack License (PBL)](LICENSE)
