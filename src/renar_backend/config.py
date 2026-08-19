#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.143586
Revised: 2026/07/29 13:55:30.394418
"""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root in the src layout (src/renar_backend/config.py -> two up).
# Anchoring here instead of the CWD keeps `.env` and a relative MEDIA_DIR
# working no matter which directory the server was launched from; a
# non-editable install should set both explicitly (absolute) anyway.
_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # The CWD `.env` (second entry) wins over the repo one when both exist.
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
    )

    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    database_url: str
    access_token_expire_minutes: int = 60 * 24 * 7  # one week
    cors_origins: list[str] = ["http://localhost:8550", "http://127.0.0.1:8550"]
    tmdb_api_key: str = ""
    # optional: TV Time import matching. Used first to retry a TMDB search
    # under TVDB's own name/aliases, and — if TMDB has no match at all — as
    # a genuine fallback identity/data source of its own; see
    # users/tvtime_import.py's TVDB fallback and docs/design-decisions.md.
    tvdb_api_key: str = ""
    # Cloudflare Turnstile (challenges.cloudflare.com) on /auth/register.
    # Site key is public — served back to clients via /auth/registration-status
    # so the register screen can build the widget without a separate config
    # round trip. Secret key never leaves the backend. Empty secret disables
    # the check entirely (dev default) rather than 503-ing registration. The
    # on/off switch itself is `registration_open`-style (see below) — a seed
    # default here, owned live by the admin panel from then on.
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    # Brevo (transactional email) for the registration/email-change confirmation
    # codes. Empty key means "log the would-be email instead of sending" — see
    # users/email_confirmation.py::send_confirmation_email — so this stays safe
    # to leave unset until a verified sending domain exists.
    brevo_api_key: str = ""
    # Seed defaults only — the admin panel (<ADMIN_PATH>/settings) owns the
    # live value from first read onward, same as the anti-abuse knobs below.
    email_sender_address: str = "noreply@renar.app"
    email_sender_name: str = "Renar"
    confirmation_code_ttl_minutes: int = 15
    email_confirmation_grace_days: int = 7  # days before an unconfirmed account is blocked at login
    unconfirmed_account_cleanup_days: int = 14  # days before an unconfirmed account is deleted
    media_dir: str = "./media"  # root of the content-addressed file store
    admin_username: str = ""  # admin panel stays 503 until both are set
    admin_password: str = ""
    # Where the admin panel lives. Rename it (e.g. /panel-x7k2) and the
    # default /admin location automatically becomes a honeypot.
    admin_path: str = "/admin"
    # Shared secret for the frontend web server's own anti-abuse guard to
    # check/report banned_ips over /svc/bans (see routers/svc.py). Empty
    # means the endpoints stay 404 to everyone, same as an unset admin panel.
    internal_service_secret: str = ""

    # anti-abuse (see security.py); the API is exposed to the open internet.
    # Limits are per IP, and one IP can be a whole office or CGNAT pool of
    # legitimate users — so limits are generous, throttling (429 + Retry-After)
    # is the normal response, and bans are reserved for unambiguous scanners.
    #
    # `abuse_guard_enabled` gates whether AbuseGuardMiddleware is installed on
    # the app at all (see main.py) — a boot-time decision. Tests turn this off
    # (single-IP traffic); toggling it in production means an `.env` edit +
    # restart, not an admin-panel action.
    #
    # Everything else below is only a seed default + DB-unreachable fallback:
    # site_settings.get_site_settings() copies these into the `site_settings`
    # DB row on first read, and the admin panel (<ADMIN_PATH>/settings) owns
    # the live value from then on — editable without a restart or `.env` edit.
    abuse_guard_enabled: bool = True
    enable_docs: bool = False  # /docs + /openapi.json advertise the API surface to scanners
    registration_open: bool = True
    turnstile_enabled: bool = True  # off falls back to IP rate-limiting only, no Turnstile keys needed
    trust_proxy_headers: bool = False  # true ONLY behind a reverse proxy/CDN (X-Forwarded-For)
    exempt_ips: list[str] = ["127.0.0.1", "::1"]  # monitoring, local tooling
    # Persisted TMDB copies (tmdb_cache table) younger than this are served
    # without contacting TMDB; older ones refresh on access and only served
    # stale when TMDB is unreachable (see tmdb/tmdb_store.py::_is_fresh).
    tmdb_db_cache_hours: int = 24
    rate_limit_per_minute: int = 600  # soft per-IP ceiling: throttles, never bans
    flood_ban_per_minute: int = 2000  # unambiguous flood: temp ban
    auth_rate_limit_per_minute: int = 30  # login/register requests per IP (throttle)
    register_per_hour_per_ip: int = 20  # new accounts per IP per hour (throttle)
    login_backoff_threshold: int = 5  # failed logins per (account, ip) before backoff
    login_backoff_account_threshold: int = 30  # failed logins per account across all IPs
    login_backoff_minutes: int = 15
    probe_ban_threshold: int = 12  # requests to nonexistent routes before a ban
    probe_window_minutes: int = 10
    ban_minutes: int = 60  # first offense; repeat offenders double, capped at 24h
    strike_ban_threshold: int = 5  # persisted offenses (see Strike) before an IP is permabanned
    # honeypot hits (/.env, /wp-login.php, ...) are PERMANENT bans stored in
    # the banned_ips table; lift them from the admin panel

    @field_validator("media_dir")
    @classmethod
    def _anchor_media_dir(cls, value: str) -> str:
        """A relative MEDIA_DIR means "relative to the repo root", not to
        whatever directory the server happened to be launched from."""
        path = Path(value)
        return str(path if path.is_absolute() else (_ROOT / path).resolve())


settings = Settings()
