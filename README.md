[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/07 13:28:52.145659 )
[//]: # (+ Revised: 	2026/07/09 08:10:02.355936 )
[//]: # ( ---------------------------------------------------------------------- )

# Xoutaim Backend

FastAPI backend for Xoutaim — save and track films, TV shows, books and YouTube videos.

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
- `PATCH /auth/profile` — update username / email / avatar
- `POST /auth/change_password` — change password
- `GET /media` — list your items (filters: `media_type`, `status_filter`, `search`)
- `POST /media` — save a film / tv_show / book / youtube item
- `GET /media/{id}` / `PATCH /media/{id}` / `DELETE /media/{id}`
- `GET /media/ratings?tmdb_id=...|title=...` — community average rating for a title
- `POST /media/{id}/rewatch` — log a rewatch of a whole item or one episode
- `GET /tmdb/search?query=...&media_type=film|tv_show` — TMDB proxy for auto-filling
  titles, years and posters (requires `TMDB_API_KEY` in `.env`; free key from
  https://www.themoviedb.org/settings/api — v3 key or v4 read token both work)
- `GET /tmdb/trending?media_type=...` / `GET /tmdb/popular?media_type=...` — Explore feeds
- `GET /tmdb/details?media_type=...&tmdb_id=...` — runtime, episode count, genres
- `GET /tmdb/season?tmdb_id=...&season_number=...` — episode list for a season
- `GET /books/search?query=...` — Open Library proxy for auto-filling title, author,
  year, page count and cover (free, no API key)
- `GET /books/trending` — Open Library daily trending feed
- `GET /books/cover/{cover_id}` — cached/redirect-safe cover image proxy
- `GET /stats` — watch time, films/episodes watched, shows completed, favorites, top genres
- `GET/PUT/POST /media/{id}/episodes...` — per-episode watched/rating tracking
  (`PUT .../episodes/{season}/{episode}`, `POST .../episodes/bulk`); responses include
  overall grade, episode average and combined score
- `GET /users/search`, `GET /users/{id}[/followers|/following|/media]`,
  `POST/DELETE /users/{id}/follow`, `GET /feed` — social graph and activity feed
- `GET/POST /comments`, `DELETE /comments/{id}`, `POST/DELETE /comments/{id}/like` —
  comments (global per title via TMDB id) with likes
- `GET /notifications` (+ `/unread_count`, `POST /{id}/read`, `POST /read_all`,
  `DELETE /{id}`, `POST /check_now`) — new-episode notifications for tracked shows
- `GET /upcoming` — countdown feed: next episodes and film premieres for tracked titles
- `GET /youtube/resolve?url=...` — title/channel/thumbnail for a YouTube URL (oEmbed, no key)
- `POST /import/tvtime` + `GET /import/tvtime/status` — import a TV Time GDPR export zip
  (runs in the background; the status endpoint reports progress)
- `GET /images/{hash}` — content-addressed stored files (avatars)
- `GET /admin` — HTML admin panel behind HTTP Basic; returns 503 until
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` are set in `.env`. Tiles:
  - **User manager** (`/users`) — per-user usage stats (logins, requests, last
    login/active), ban/unban, delete. Clicking a username opens a **detail page**
    (`/users/{id}`) with account actions (edit username/email, set a new password,
    ban, delete — `POST /users/{id}/edit`, `/password`), inline-SVG per-day charts
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

The suite spins up the app against a throwaway SQLite database (no `.env` or
API keys needed) and covers every endpoint's happy and error paths.

## Notes

- SQLite by default (`xoutaim.db`); set `DATABASE_URL` in `.env` for Postgres.
- Schema is owned by Alembic (`alembic/versions/`); the app no longer creates tables itself.
  Migrations run in batch mode so ALTERs work on SQLite too.

## License

[PayBack License (PBL)](LICENSE)
