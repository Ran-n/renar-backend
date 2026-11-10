#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.587996
Revised: 2026/11/09 23:36:43.827657

Admin sign-in page: username, password and the 6-digit authenticator code
(TOTP). A correct triple sets the ``renar_admin`` session cookie (see
users/admin_session.py); a wrong one re-renders the page with one generic
error and records an abuse strike for the IP, unless it is in
``site_settings.exempt_ips``.
"""

import html
import logging
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import site_settings
from ...config import settings
from ...users import admin_session, security
from ._html import _BASE_CSS, _FAVICON, _P, _RESPONSIVE_CSS

router = APIRouter()
_log = logging.getLogger(__name__)

_LOGIN_CSS = """
    .login-wrap { min-height: calc(100vh - 60px); display: flex; align-items: center; justify-content: center;
      padding: 1.5rem 1rem; }
    .login-card { width: 100%; max-width: 360px; background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.5rem 1.4rem; display: flex; flex-direction: column; gap: .9rem; }
    .login-card h1 { font-size: 1.05rem; font-weight: 650; color: var(--text); margin: 0; }
    .login-card label { display: flex; flex-direction: column; gap: .3rem; font-size: .74rem; color: var(--text-2); }
    .login-card input { background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 8px; padding: .55rem .7rem; font-size: .9rem; font-family: inherit; }
    .login-card input:focus { outline: none; border-color: var(--accent); }
    .login-error { background: rgba(251,73,52,.1); border: 1px solid rgba(251,73,52,.3); color: #fb4934;
      border-radius: 8px; padding: .5rem .7rem; font-size: .8rem; }
    .login-btn { background: var(--accent); color: var(--bg); border: none; border-radius: 8px;
      padding: .6rem; font-size: .88rem; font-weight: 650; cursor: pointer; font-family: inherit; }
    .login-btn:hover { opacity: .9; }
"""


def safe_next(target: str | None) -> str:
    """Only paths inside the admin panel; anything else (``//evil.com``,
    ``https://…``) lands on the dashboard, so the login can't be an open redirect."""
    if target and (target == _P or target.startswith(f"{_P}/")) and "\\" not in target and "/../" not in f"{target}/":
        return target
    return _P


def login_url(next_path: str) -> str:
    return f"{_P}/login?next={quote(next_path, safe='')}"


def _page(*, username: str = "", next_path: str = _P, error: str | None = None) -> str:
    error_html = f'<div class="login-error" role="alert">{html.escape(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in &middot; renar admin</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_LOGIN_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>
  <header class="topbar">
    <div class="logo">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
    </div>
    <div class="brand">
      <span class="brand-name">Admin</span>
      <span class="brand-sub">renar</span>
    </div>
  </header>
  <main class="login-wrap">
    <form class="login-card" method="post" action="{_P}/login">
      <h1>Sign in</h1>
      {error_html}
      <input type="hidden" name="next" value="{html.escape(next_path)}">
      <label>Username
        <input name="username" autocomplete="username" required value="{html.escape(username)}">
      </label>
      <label>Password
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <label>Authenticator code
        <input name="code" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9 ]{{6,7}}"
               maxlength="7" required>
      </label>
      <button class="login-btn" type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>"""


def _require_configured() -> None:
    if not admin_session.admin_configured():
        raise HTTPException(
            status_code=503, detail="Admin panel not configured (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TOTP_SECRET)"
        )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, next: str | None = None):
    _require_configured()
    if admin_session.read_session(request.cookies.get(admin_session.COOKIE_NAME)):
        return RedirectResponse(_P, status_code=303)
    return HTMLResponse(_page(next_path=safe_next(next)))


def _strike(ip: str) -> None:
    """Record a failed sign-in as an abuse strike (temp ban, permaban once it
    repeats), never for an exempt IP."""
    if ip in site_settings.current().exempt_ips:
        return
    count, until = security.strike_and_maybe_ban(ip, "admin login failed")
    if until is None:
        security.permaban(ip, f"{count} repeated offenses: admin login failed")
    else:
        security.note_temp_ban(ip, until)
        _log.warning("BANNED %s until %d (offense #%d): admin login failed", ip, until, count)


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    code: str = Form(""),
    next: str = Form(""),
):
    _require_configured()
    ip = security.client_ip(request)
    target = safe_next(next)
    if not admin_session.verify_login(username, password, code):
        _log.warning("admin login failed ip=%s username=%r", ip, username)
        _strike(ip)
        return HTMLResponse(
            _page(username=username, next_path=target, error="Wrong username, password or code."), status_code=401
        )
    _log.info("admin login ok ip=%s", ip)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        admin_session.COOKIE_NAME,
        admin_session.issue_session(settings.admin_username),
        max_age=admin_session.SESSION_SECONDS,
        path=_P,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout", include_in_schema=False)
def logout(request: Request):
    response = RedirectResponse(f"{_P}/login", status_code=303)
    response.delete_cookie(
        admin_session.COOKIE_NAME, path=_P, httponly=True, samesite="strict", secure=request.url.scheme == "https"
    )
    return response


def session_expired_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Session expired &middot; renar admin</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_LOGIN_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>
  <main class="login-wrap">
    <div class="login-card">
      <h1>Session expired — sign in again</h1>
      <p style="color:var(--text-2);font-size:.85rem;margin:0">Nothing was changed. Sign in, then repeat the action.</p>
      <a class="login-btn" style="text-align:center;text-decoration:none" href="{_P}/login">Sign in</a>
    </div>
  </main>
</body>
</html>"""
