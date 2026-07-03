# Xoutaim Backend

FastAPI backend for Xoutaim — save and track films, TV shows and YouTube videos.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit SECRET_KEY
```

## Run

```powershell
alembic upgrade head       # apply database migrations (first run and after every pull)
uvicorn app.main:app --reload
```

## Changing the schema

Edit `app/models.py`, then:

```powershell
alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/ before applying!
alembic upgrade head
```

API docs: http://127.0.0.1:8000/docs

## Endpoints

- `POST /auth/register` — create account
- `POST /auth/login` — get JWT token (form fields: username, password; username also accepts email)
- `GET /auth/me` — current user; `DELETE /auth/me` — delete account (cleans up all data)
- `POST /auth/change_password` — change password
- `GET /media` — list your items (filters: `media_type`, `status_filter`, `search`)
- `POST /media` — save a film / tv_show / youtube item
- `GET /media/{id}` / `PATCH /media/{id}` / `DELETE /media/{id}`
- `GET /tmdb/search?query=...&media_type=film|tv_show` — TMDB proxy for auto-filling
  titles, years and posters (requires `TMDB_API_KEY` in `.env`; free key from
  https://www.themoviedb.org/settings/api — v3 key or v4 read token both work)
- `GET /tmdb/trending?media_type=...` / `GET /tmdb/popular?media_type=...` — Explore feeds
- `GET /tmdb/details?media_type=...&tmdb_id=...` — runtime, episode count, genres
- `GET /tmdb/season?tmdb_id=...&season_number=...` — episode list for a season
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

TMDB responses are cached in memory for 30 minutes.

A background task checks every `EPISODE_CHECK_MINUTES` (default 360) whether any
tracked show aired a new episode in the last 7 days, and creates a notification
per user — skipping episodes the user already marked watched.

## Notes

- SQLite by default (`xoutaim.db`); set `DATABASE_URL` in `.env` for Postgres.
- Schema is owned by Alembic (`alembic/versions/`); the app no longer creates tables itself.
  Migrations run in batch mode so ALTERs work on SQLite too.
