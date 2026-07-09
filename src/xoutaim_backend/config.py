#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.143586
Revised: 2026/07/07 13:25:14.143586
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    database_url: str = "sqlite:///./xoutaim.db"
    access_token_expire_minutes: int = 60 * 24 * 7  # one week
    cors_origins: list[str] = ["http://localhost:8550", "http://127.0.0.1:8550"]
    tmdb_api_key: str = ""
    tvdb_api_key: str = ""  # optional: fallback lookup for TV Time import matching
    episode_check_minutes: int = 360  # how often to look for new episodes
    media_dir: str = "./media"  # root of the content-addressed file store
    admin_username: str = ""  # admin panel stays 503 until both are set
    admin_password: str = ""
    # Where the admin panel lives. Rename it (e.g. /panel-x7k2) and the
    # default /admin location automatically becomes a honeypot.
    admin_path: str = "/admin"

    # anti-abuse (see security.py); the API is exposed to the open internet.
    # Limits are per IP, and one IP can be a whole office or CGNAT pool of
    # legitimate users — so limits are generous, throttling (429 + Retry-After)
    # is the normal response, and bans are reserved for unambiguous scanners.
    abuse_guard_enabled: bool = True  # tests turn this off (single-IP traffic)
    enable_docs: bool = False  # /docs + /openapi.json advertise the API surface to scanners
    registration_open: bool = True
    trust_proxy_headers: bool = False  # true ONLY behind a reverse proxy/CDN (X-Forwarded-For)
    exempt_ips: list[str] = ["127.0.0.1", "::1"]  # monitoring, local tooling
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


settings = Settings()
