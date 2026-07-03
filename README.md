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
uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs

## Endpoints

- `POST /auth/register` — create account
- `POST /auth/login` — get JWT token (form fields: username, password; username also accepts email)
- `GET /auth/me` — current user
- `GET /media` — list your items (filters: `media_type`, `status_filter`, `search`)
- `POST /media` — save a film / tv_show / youtube item
- `GET /media/{id}` / `PATCH /media/{id}` / `DELETE /media/{id}`
- `GET /tmdb/search?query=...&media_type=film|tv_show` — TMDB proxy for auto-filling
  titles, years and posters (requires `TMDB_API_KEY` in `.env`; free key from
  https://www.themoviedb.org/settings/api — v3 key or v4 read token both work)

## Notes

- SQLite by default (`xoutaim.db`); set `DATABASE_URL` in `.env` for Postgres.
- Tables are auto-created on startup. Introduce Alembic before changing models in production.
