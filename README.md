[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/07 13:28:52.145659 )
[//]: # (+ Revised: 	2026/11/10 13:53:25.931247 )
[//]: # ( ---------------------------------------------------------------------- )

# Renar Backend

FastAPI backend for Renar — your personal media tracker (films and TV shows).

## Setup (uses [uv](https://docs.astral.sh/uv/))

```powershell
uv sync
copy .env.example .env   # then edit SECRET_KEY
```

## Run

```powershell
uv run alembic upgrade head   # apply database migrations (first run and after every pull)
uv run be                     # uvicorn with auto-reload, HTTPS when certs/ has a cert
```

### Updating the server

The admin panel's **Server Update** page (`<ADMIN_PATH>/update`) shows the
running version and what's newer, and its **Update** button installs it.
The source depends on the project directory:

- **Git checkout** (`.git` present, e.g. the dev PC): the newer commits on
  `origin/master`. The update stages the new `pyproject.toml`, `uv.lock`
  and `alembic/`, runs `uv sync --locked` and `alembic upgrade head`, then
  fast-forwards the checkout. Rollback is `git reset --hard` to the old
  commit, so the button only works on `master` with no uncommitted changes
  and no unpushed commits, and `git fetch` has to work.
- **Anything else** (a tarball deploy, e.g. prod): the latest release from
  `UPDATE_RELEASE_URL` (GitHub's releases by default) and its notes. The
  update downloads `renar_backend-<version>.tar.gz`, checks it against the
  `.tar.gz.b3` BLAKE3 sum next to it and unpacks it into
  `.self-update/stage`. It then moves the new `pyproject.toml`, `uv.lock`,
  `alembic/` and the rest into place, syncs, migrates, and finally swaps
  `src/`. Rollback moves the old files back from `.self-update/previous`,
  where they also stay after a success until the next update. The release
  needs both assets.

Either way uvicorn's reloader picks up the new code; the server process is
never stopped, so this works the same under systemd or a console. `.env`,
`media/`, `logs/`, `certs/` and `.venv/` are never touched. If any step
fails, or the new code doesn't come up within 2 minutes, it rolls back
(migration downgraded, old files back, `uv sync`) and the page says so,
with the log path (`logs/self-update-<timestamp>.log`).

The button is also disabled, with the reason, unless the server runs under
`uv run be` and no other update is running. The whole project directory
must be writable by the server's user (under systemd with
`ProtectSystem=strict`, `ReadWritePaths=` must cover it, not only `media/`
and `logs/`). A migration must not import app code (it runs before the code
swap). On Windows, `uv sync` can't replace a compiled package the running
server has loaded; such an update rolls back and has to be done by hand.

By hand, from a git checkout:

```powershell
git pull --ff-only origin master
uv sync --locked              # --no-dev on prod
uv run alembic upgrade head
# uv run be reloads by itself; otherwise restart it
```

## HTTPS

Local development runs over plain HTTP (traffic never leaves the machine /
home network). For TLS, uvicorn supports it natively — no proxy needed:

```powershell
uv run uvicorn renar_backend.main:asgi_app --ssl-keyfile key.pem --ssl-certfile cert.pem
```

A public deployment should get certificates from the platform or Let's Encrypt.

## Docs

See [docs/](docs/) for a full explanation of every `.env` setting, how the
anti-abuse (rate limiting / banning) system works, and the reasoning behind
the data model and other non-obvious architecture choices.

## Changing the schema

Edit `src/renar_backend/models.py`, then:

```powershell
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/ before applying!
uv run alembic upgrade head
```

API docs: http://127.0.0.1:8000/docs

## Endpoints

- `GET /app-releases/latest?platform=android-<abi>` — unauthenticated; newest
  APK for that ABI (`version`, `size_bytes`, `sha256`, `blake3`, `notes`,
  `download_url`), 404 when none, 422 for an unknown platform
- `GET /app-releases/{id}/download` — unauthenticated; the APK, named
  `renar-<version>-<abi>.apk`
- `GET /auth/registration-status` — unauthenticated; returns `registration_open` and
  `invite_only` so the signup screen can render the invite-code field before submission
- `POST /auth/register` — create account (also accepts `invite_code` when
  `site_settings.invite_only` is `true`)
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
- `POST /media` — save a film / tv_show item
- `GET /media/{id}` / `PATCH /media/{id}` / `DELETE /media/{id}`
- `GET /media/ratings?tmdb_id=...|title=...` — community average rating for a title
- `POST /media/ratings/batch` — community average rating for up to 100 tmdb_ids at once
  (Explore's result grid, one request per page instead of one per card)
- `POST /media/{id}/rewatch` / `POST /media/{id}/undo-rewatch` — log or undo the
  latest rewatch of a whole item or one episode
- `GET /media/{id}/rewatch-events` / `DELETE /media/{id}/rewatch-events/{event_id}`
  — list individual rewatch events (newest first) or remove one specific event
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
- `GET /premium/palette` — suggested color swatches for every premium color picker
  (not an enforced allowlist — any well-formed hex is accepted)
- `PATCH /premium/style` — premium: set avatar ring color / username color /
  Home season & series progress colors / per-tier Upcoming countdown-pill colors
  (`countdown_colors`, keyed `urgent`/`soon`/`later`/`past`) / per-status Library
  colors (explicit null clears one; `countdown_colors` and `status_colors` merge
  per-key)
- `POST/DELETE /premium/verification-request` — request or withdraw the verified-badge
  request (withdrawal needs no active premium; granting is admin-only, see below)
- `GET /notifications` (+ `/unread_count`, `POST /{id}/read`, `POST /read_all`,
  `DELETE /{id}`, `POST /check_now`) — new-episode notifications for tracked shows
- `GET /upcoming` (+ `/history`) — countdown feed: next episodes and film premieres
  for tracked titles, plus a history of past ones
- `POST /import/tvtime` + `GET /import/tvtime/status` — import a TV Time GDPR export zip
  (runs in the background; the status endpoint reports progress)
- `GET /images/{hash}` — content-addressed stored files (avatars, profile
  backgrounds, custom posters, custom backdrops, episode stills)
- `GET/POST /svc/bans`, `POST /svc/strikes` — machine-to-machine, guarded by
  `INTERNAL_SERVICE_SECRET` (not the admin session): lets the frontend's own
  web-server anti-abuse guard share this server's persisted ban/strike state
  (see [docs/anti-abuse.md](docs/anti-abuse.md)); deliberately not under `/internal/`,
  which is honeypot bait
- `GET /admin` — HTML admin panel behind a login page (password +
  authenticator code, then an 8-hour session cookie; Log out on every page);
  returns 503 until `ADMIN_USERNAME`, `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET`
  are set in `.env` (see [Setting up admin sign-in](#setting-up-admin-sign-in)).
  Tiles:
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
  - **Site Settings** (`/settings`) — toggle registration open/invite-only and tune
    all anti-abuse limits (rate limits, flood threshold, login backoff, probe
    detection, ban duration/escalation, and periodic task toggles) without a restart.
  - **Invite Codes** (`/invites`) — generate random 32-char invite codes with
    configurable max-uses (single/5/10/25/unlimited/custom) and optional expiry;
    revoke active codes on-page.
  - **Server Update** (`/update`) — one-click update (git checkout:
    `origin/master`; otherwise the latest release tarball, BLAKE3-checked)
    with automatic rollback, see [Updating the server](#updating-the-server).
  - **App Releases** (`/app-releases`) — every uploaded Android APK per ABI,
    newest first, with a Latest pill and a delete button. Uploads come from
    renar-frontend's `uv run build apk --split --publish`, which calls
    `POST <ADMIN_PATH>/app-releases` (multipart `file`, `platform`, `version`,
    optional `notes`; 201 new, 200 identical re-upload, 409 same version with
    different bytes, 413 over 200 MiB, 422 not an APK).

#### Setting up admin sign-in

On the server host (over SSH on prod):

1. `uv run admin-totp` prints a new secret, a QR code and the
   `ADMIN_TOTP_SECRET=…` line. Scan the QR with an authenticator app
   (Aegis, Google Authenticator, 1Password, …) and put the line in `.env`.
2. For `--publish` uploads, also set `ADMIN_API_TOKEN` (see
   [docs/environment-variables.md](docs/environment-variables.md#admin-panel)).
3. Restart the server.

Every failed sign-in is an abuse strike (temp ban, then a permanent ban),
except from an IP in Exempt IPs. Locked yourself out? `uv run admin-unban
<ip>` lifts every ban on that IP; restart the server afterwards so it
forgets its in-memory copy (`sudo systemctl restart renar-backend` on prod).

TMDB responses are cached in memory for 6 hours.

Background tasks (episode check, episode history sync, film release date
refresh, TMDB metadata resync, ban-strike cleanup) each run on their own
schedule and can be independently enabled/disabled and rescheduled from
`<ADMIN_PATH>/periodic-tasks`.

## Tests

```powershell
uv run pytest
```

The suite spins up the app against a throwaway schema on the local Postgres
server (no `.env` or API keys needed) and covers every endpoint's happy and
error paths. That default run is the fast unit suite plus a few always-on
categories (`property`, `fuzz`, `snapshot`); everything that spins up a real
process or hits the network is gated behind its own marker and selected
explicitly:

```powershell
uv run pytest -m integration        # real uvicorn process on a real socket
uv run pytest -m smoke              # fastest post-boot sanity check
uv run pytest -m regression         # curated critical-path subset
uv run pytest -m security           # bandit (SAST) + pip-audit (needs network)
uv run pytest -m load               # short headless locust burst
```

Mutation testing (`mutmut`, config in `pyproject.toml`'s `[tool.mutmut]`)
needs WSL or Linux — it has no native Windows support and isn't runnable
from a plain PowerShell/cmd shell.

## Notes

- Requires Postgres; set `DATABASE_URL` in `.env` (see `.env.example`).
- Schema is owned by Alembic (`alembic/versions/`); the app no longer creates tables itself.

## License

[PayBack License (PBL)](LICENSE)
