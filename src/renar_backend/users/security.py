#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.282446
Revised: 2026/09/02 10:57:11.316476

In-app defenses against the scanner/bot traffic a publicly exposed server
attracts, tuned so that legitimate users are never banned:

- Honeypot paths (/.env, /wp-login.php, ...) that no real client ever
  requests: one hit = long ban. Zero false-positive risk.
- Probe detection: only requests for paths that match NO registered route
  count (a real client hitting a 404 on an existing endpoint — deleted
  item, stale link — never counts).
- Rate limiting is throttle-first: exceeding the soft limit answers 429
  until the window clears; only a flood far above it earns a ban. Many
  users share one IP (offices, mobile CGNAT), so bans are a last resort.
- Login protection is per-account (see check_login_allowed), not per-IP,
  so credential stuffing is blunted without locking out a whole office.

Rate-limit windows (hits/auth_hits/probe_hits) are in-memory and reset on
restart by design — that's fine, a scanner just re-earns its ban within
seconds. But the ban escalation itself (offense count + any active
temporary ban) is backed by the `strikes` table (one small row per
offending IP, upserted in place — never one row per request) so a restart
doesn't grant amnesty. If you scale to multiple workers/instances, the
in-memory rate-limit windows would need to move to Redis too.

When deployed behind a reverse proxy or CDN, set TRUST_PROXY_HEADERS=true
so the real client IP is read from X-Forwarded-For (rightmost entry, the
one appended by your proxy). Without it every request would appear to
come from the proxy and one bad actor could get the proxy IP throttled.
"""

import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Match

from .. import site_settings, task_runs
from ..config import settings
from ..database import SessionLocal
from ..models import BannedIP, Strike, utcnow

_log = logging.getLogger(__name__)

_MINUTE = 60.0
_HOUR = 3600.0

# Endpoints where each request is a credential guess.
_AUTH_PATHS = ("/auth/login", "/auth/register")
# High-frequency infrastructure endpoints (load balancer health checks)
# that must never eat into a client's budget.
_UNCOUNTED_PATHS = ("/health", "/robots.txt")

# Paths only vulnerability scanners request. A hit means a PERMANENT ban,
# persisted to the database (lifted only via the admin panel). The app must
# never grow a real route that collides with these.
HONEYPOT_PATHS = frozenset({
    "/.env",
    "/.env.local",
    "/.env.production",
    "/.aws/credentials",
    "/.git/config",
    "/id_rsa",
    "/config.php",
    "/xmlrpc.php",
    "/wp-login.php",
    "/server-status",
    "/mcp",
    "/jsonrpc",
})
HONEYPOT_PREFIXES = (
    "/wp-admin",
    "/wp-content",
    "/wp-includes",
    "/phpmyadmin",
    "/cgi-bin/",
    "/vendor/",
    "/.git/",
    "/internal/",  # bait advertised in robots.txt; nothing real lives here
)

# Well-behaved crawlers respect this and go away (it's an API, there is
# nothing to index). Scanners that fetch robots.txt hunting for "hidden"
# paths and then request /internal/ walk straight into the honeypot.
_ROBOTS_TXT = "User-agent: *\nDisallow: /internal/\nDisallow: /\n"


def _is_honeypot(path: str) -> bool:
    if path in HONEYPOT_PATHS or path.startswith(HONEYPOT_PREFIXES):
        return True
    # When the real admin panel is renamed via ADMIN_PATH, the default
    # /admin location becomes bait too — scanners hammer it constantly.
    if settings.admin_path.rstrip("/") != "/admin":
        return path == "/admin" or path.startswith("/admin/")
    return False


# ---------------------------------------------------------------------------
# Permanent bans, persisted in the banned_ips table so they survive
# restarts. Kept mirrored in an in-memory set for per-request checks; the
# admin panel (/admin/bans, wherever ADMIN_PATH puts it) can lift them.
# ---------------------------------------------------------------------------

_permabanned: set[str] = set()
_permabans_loaded = False


def _load_permabans() -> None:
    global _permabans_loaded
    try:
        with SessionLocal() as db:
            _permabanned.update(ip for (ip,) in db.query(BannedIP.ip))
        _permabans_loaded = True
    except Exception:  # e.g. migrations not run yet — retry on next request
        _log.exception("could not load banned_ips; will retry")


def permaban(ip: str, reason: str) -> None:
    _permabanned.add(ip)  # effective immediately even if the DB write fails
    try:
        with SessionLocal() as db:
            try:
                with db.begin_nested():
                    db.add(BannedIP(ip=ip, reason=reason))
            except IntegrityError:
                pass  # concurrent call already persisted the row; in-memory set is authoritative
            db.commit()
    except Exception:
        _log.exception("could not persist permaban for %s (in-memory ban still active)", ip)
        raise
    _log.warning("PERMABANNED %s: %s", ip, reason)


def lift_permaban(ip: str) -> None:
    """In-memory half of an unban; the caller removes the DB row."""
    _permabanned.discard(ip)


# ---------------------------------------------------------------------------
# Repeat-offender strikes, persisted so escalation survives a restart. One
# row per IP (upserted), never one row per offense — bounded by the number
# of distinct offenders, not by request volume.
# ---------------------------------------------------------------------------

_last_strike_cleanup = 0.0


def strike_and_maybe_ban(ip: str, reason: str) -> tuple[int, float | None]:
    """Record an offense for `ip`, returning (strike count, temp-ban-until).

    A day with no new offense forgives the streak (count resets to 1).
    `until` is a `time.time()`-comparable epoch, or None once the caller
    should permaban instead of temp-banning (count hit the threshold).

    Public: also called from routers/svc.py so the frontend's own guard can
    record a strike (e.g. a flood ban) through the same persisted escalation
    used here, instead of duplicating the logic.
    """
    now_dt = datetime.now(UTC)
    try:
        with SessionLocal() as db:
            # with_for_update() serialises concurrent offenses from the same IP:
            # two simultaneous ban triggers both read the row, the second waits
            # until the first commits, then reads the already-incremented count.
            strike = db.query(Strike).filter(Strike.ip == ip).with_for_update().first()
            if strike is None:
                try:
                    with db.begin_nested():
                        strike = Strike(ip=ip, count=1, reason=reason, last_offense_at=now_dt)
                        db.add(strike)
                except IntegrityError:
                    # Another request raced us to the first INSERT; re-read with lock.
                    strike = db.query(Strike).filter(Strike.ip == ip).with_for_update().first()
                    if strike is None:
                        _log.error("strike for %s neither insertable nor findable after race", ip)
                        return 1, time.time() + site_settings.current().ban_minutes * _MINUTE
                    last = strike.last_offense_at
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=UTC)
                    strike.count = 1 if now_dt - last > timedelta(hours=24) else strike.count + 1
                    strike.reason = reason
                    strike.last_offense_at = now_dt
            else:
                last = strike.last_offense_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                strike.count = 1 if now_dt - last > timedelta(hours=24) else strike.count + 1
                strike.reason = reason
                strike.last_offense_at = now_dt
            count = strike.count
            ss = site_settings.current()
            if count >= ss.strike_ban_threshold:
                strike.banned_until = None
                db.commit()
                return count, None
            duration = min(ss.ban_minutes * 2 ** (count - 1), 24 * 60)  # escalates, cap 24h
            until_dt = now_dt + timedelta(minutes=duration)
            strike.banned_until = until_dt
            db.commit()
            return count, time.time() + duration * _MINUTE
    except Exception:
        _log.exception("could not persist strike for %s (falling back to a single-offense ban)", ip)
        return 1, time.time() + site_settings.current().ban_minutes * _MINUTE


def load_active_temp_bans() -> dict[str, float]:
    """Rebuild in-memory `banned_until` from the DB on startup.

    Public: also called from routers/svc.py so the frontend can preload the
    same active temp bans (not just permabans) on its own startup.
    """
    now_dt = datetime.now(UTC)
    result: dict[str, float] = {}
    try:
        with SessionLocal() as db:
            rows = db.query(Strike.ip, Strike.banned_until).filter(Strike.banned_until.isnot(None)).all()
        for ip, banned_until in rows:
            if banned_until.tzinfo is None:
                banned_until = banned_until.replace(tzinfo=UTC)
            if banned_until > now_dt:
                result[ip] = time.time() + (banned_until - now_dt).total_seconds()
    except Exception:
        _log.exception("could not load active strikes; temp bans will re-accumulate")
    return result


def _cleanup_old_strikes(now: float) -> None:
    """Drop strike rows nobody has touched in 30 days, at most once per the
    admin-configurable interval (task_runs, default 60 minutes)."""
    global _last_strike_cleanup
    if not task_runs.is_enabled("strike_cleanup"):
        return
    interval_seconds = task_runs.get_interval_minutes("strike_cleanup") * _MINUTE
    if now - _last_strike_cleanup < interval_seconds:
        return
    _last_strike_cleanup = now
    started = utcnow()
    cutoff = datetime.now(UTC) - timedelta(days=30)
    try:
        with SessionLocal() as db:
            deleted = db.query(Strike).filter(Strike.last_offense_at < cutoff).delete(synchronize_session=False)
            db.commit()
        task_runs.record_run("strike_cleanup", started, "ok", f"{deleted} strikes dropped")
    except Exception:
        _log.exception("could not clean up old strikes")
        task_runs.record_run("strike_cleanup", started, "error", "cleanup failed, see server logs")


# ---------------------------------------------------------------------------
# Per-account login backoff (used by the /auth/login endpoint, not the
# middleware — only the endpoint knows the username and the outcome).
# Two layers:
#   - per (account, ip): stops a single source guessing one account, while
#     the account owner on another IP is unaffected.
#   - per account across all IPs, with a much higher ceiling: blunts
#     distributed credential stuffing without letting one griefer lock a
#     victim out by spamming failures.
# ---------------------------------------------------------------------------

_login_failures_by_key: dict[str, deque[float]] = defaultdict(deque)
_login_failures_by_account: dict[str, deque[float]] = defaultdict(deque)


def _account_key(username: str) -> str:
    return username.strip().lower()


def check_login_allowed(username: str, ip: str) -> None:
    """Raise 429 (with Retry-After) if this account is under backoff."""
    if not settings.abuse_guard_enabled:
        return
    now = time.time()
    ss = site_settings.current()
    window = ss.login_backoff_minutes * _MINUTE
    account = _account_key(username)

    for tracker, key, limit in (
        (_login_failures_by_key, f"{account}|{ip}", ss.login_backoff_threshold),
        (_login_failures_by_account, account, ss.login_backoff_account_threshold),
    ):
        dq = tracker[key]
        _prune(dq, now - window)
        if len(dq) >= limit:
            retry_after = int(dq[0] + window - now) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many failed sign-in attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


def note_login_failure(username: str, ip: str) -> None:
    if not settings.abuse_guard_enabled:
        return
    now = time.time()
    account = _account_key(username)
    _login_failures_by_key[f"{account}|{ip}"].append(now)
    _login_failures_by_account[account].append(now)


def note_login_success(username: str, ip: str) -> None:
    account = _account_key(username)
    _login_failures_by_key.pop(f"{account}|{ip}", None)
    _login_failures_by_account.pop(account, None)


def reset_login_backoff(username: str) -> None:
    """Clear all recorded failures for this account, across every IP (admin action)."""
    account = _account_key(username)
    _login_failures_by_account.pop(account, None)
    prefix = f"{account}|"
    for key in [k for k in _login_failures_by_key if k.startswith(prefix)]:
        _login_failures_by_key.pop(key, None)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _prune(dq: deque[float], cutoff: float) -> None:
    while dq and dq[0] < cutoff:
        dq.popleft()


def client_ip(request: Request) -> str:
    if site_settings.current().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # rightmost entry = the hop appended by our own proxy;
            # anything left of it is client-supplied and spoofable
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _has_valid_token(request: Request) -> bool:
    """A cryptographically valid session token — unforgeable, so its holder
    is a real (identifiable) user, never an anonymous scanner."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    try:
        jwt.decode(header[7:], settings.secret_key, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


def _matches_no_route(request: Request) -> bool:
    """True if the path doesn't belong to any registered route (a probe)."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match != Match.NONE:
            return False
    return True


def _too_many(retry_after: int = 60) -> JSONResponse:
    return JSONResponse(
        {"detail": "Too many requests"},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


class AbuseGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.banned_until: dict[str, float] = {}
        self._temp_bans_loaded = False
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.auth_hits: dict[str, deque[float]] = defaultdict(deque)
        self.register_hits: dict[str, deque[float]] = defaultdict(deque)
        self.probe_hits: dict[str, deque[float]] = defaultdict(deque)

    def _ban(self, ip: str, reason: str) -> None:
        count, until = strike_and_maybe_ban(ip, reason)
        if until is None:
            permaban(ip, f"{count} repeated offenses: {reason}")
            self.banned_until.pop(ip, None)
            return
        self.banned_until[ip] = until
        _log.warning("BANNED %s until %d (offense #%d): %s", ip, until, count, reason)

    def _sweep(self, now: float) -> None:
        """Keep tracking dicts bounded under sustained scanning."""
        ss = site_settings.current()
        for tracker, window in (
            (self.hits, _MINUTE),
            (self.auth_hits, _MINUTE),
            (self.register_hits, _HOUR),
            (self.probe_hits, ss.probe_window_minutes * _MINUTE),
            (_login_failures_by_key, ss.login_backoff_minutes * _MINUTE),
            (_login_failures_by_account, ss.login_backoff_minutes * _MINUTE),
        ):
            if len(tracker) > 10_000:
                for key in [k for k, dq in tracker.items() if not dq or dq[-1] < now - window]:
                    del tracker[key]
        for ip in [ip for ip, until in self.banned_until.items() if until < now]:
            del self.banned_until[ip]
        _cleanup_old_strikes(now)

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = client_ip(request)
        now = time.time()
        ss = site_settings.current()

        if ip in ss.exempt_ips:
            return await call_next(request)

        if not _permabans_loaded:
            _load_permabans()
        if ip in _permabanned:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        if not self._temp_bans_loaded:
            self.banned_until.update(load_active_temp_bans())
            self._temp_bans_loaded = True

        until = self.banned_until.get(ip)
        if until is not None:
            if now < until:
                return _too_many(retry_after=int(until - now) + 1)
            del self.banned_until[ip]

        path = request.url.path

        if path == "/robots.txt":
            return PlainTextResponse(_ROBOTS_TXT)

        if _is_honeypot(path):
            permaban(ip, f"honeypot hit: {path}")
            # look like any other missing path; don't reveal the trap
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        counted = path not in _UNCOUNTED_PATHS
        if counted:
            hits = self.hits[ip]
            _prune(hits, now - _MINUTE)
            hits.append(now)
            if len(hits) > ss.flood_ban_per_minute:
                self._ban(ip, f"flood: >{ss.flood_ban_per_minute} req/min")
                return _too_many()
            if len(hits) > ss.rate_limit_per_minute:
                # over the soft limit: throttle, never ban — this can be a
                # busy office or CGNAT pool, not necessarily an attack
                return _too_many()

        if path in _AUTH_PATHS:
            auth_hits = self.auth_hits[ip]
            _prune(auth_hits, now - _MINUTE)
            auth_hits.append(now)
            if len(auth_hits) > ss.auth_rate_limit_per_minute:
                return _too_many()

        if path == "/auth/register" and request.method == "POST":
            reg_hits = self.register_hits[ip]
            _prune(reg_hits, now - _HOUR)
            reg_hits.append(now)
            if len(reg_hits) > ss.register_per_hour_per_ip:
                return _too_many(retry_after=int(reg_hits[0] + _HOUR - now) + 1)

        response = await call_next(request)

        # Scanners map an API by walking paths that don't exist here at all.
        # Only routeless paths count, so a real client 404 (deleted media,
        # stale link) or 405 on an existing endpoint can never trip this.
        # A valid signed token also exempts: an outdated app calling an
        # endpoint that no longer exists must not get its users banned.
        if response.status_code == 404 and _matches_no_route(request) and not _has_valid_token(request):
            probes = self.probe_hits[ip]
            _prune(probes, now - ss.probe_window_minutes * _MINUTE)
            probes.append(now)
            if len(probes) >= ss.probe_ban_threshold:
                self._ban(
                    ip,
                    f"probing: {len(probes)} unknown paths in {ss.probe_window_minutes} min (last: {path})",
                )

        self._sweep(now)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers.

    The admin panel (settings.admin_path) is server-rendered HTML with
    inline <style>/<script> blocks, so it gets a CSP that permits those; the
    Turnstile widget page (users/turnstile.py's widget_html) is also
    server-rendered HTML — it needs its own inline <style>/<script> plus
    Cloudflare's own https://challenges.cloudflare.com script and iframe —
    so it gets a third, narrowly-scoped CSP; every other route is JSON-only
    and gets the strict `default-src 'none'`.

    The admin panel also gets `Referrer-Policy: same-origin` instead of
    `no-referrer`: per the Fetch spec, the Origin header on non-GET
    non-CORS requests follows the page's referrer policy, so under
    `no-referrer` browsers send `Origin: null` on the panel's own form
    POSTs — which OriginCheckMiddleware (rightly) rejects. `same-origin`
    still keeps the referrer from leaking off-site.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(settings.admin_path.rstrip("/") or "/admin"):
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
            )
        elif request.url.path.startswith("/auth/turnstile-widget/"):
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline' https://challenges.cloudflare.com; "
                "frame-src https://challenges.cloudflare.com; "
                "connect-src 'self' https://challenges.cloudflare.com; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Rejects cross-site browser requests that carry a mismatched Origin.

    Auth here is a bearer token, not a cookie, so classic CSRF (a forged
    request riding the victim's session cookie) doesn't apply. This is
    defense-in-depth for the case a browser client sends the token anyway.
    Non-browser clients (the app, curl, server-to-server) don't send an
    Origin header at all, so they're unaffected.

    Browsers send Origin on POST/PUT/PATCH/DELETE even for same-origin
    requests (e.g. the admin panel's own <form method="post"> actions), so
    the request's own origin must be accepted alongside the CORS allowlist.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin:
                self_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
                if origin != self_origin and origin not in settings.cors_origins:
                    _log.warning(
                        "blocked %s %s: Origin %r matches neither self (%s) nor CORS_ORIGINS %s",
                        request.method,
                        request.url.path,
                        origin,
                        self_origin,
                        settings.cors_origins,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Origin not allowed"},
                    )
        return await call_next(request)
