#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 19:32:52.480946

Admin site-settings page: view and save registration mode, rate limits, and
abuse thresholds. Periodic-task toggles/intervals live on their own page
(routers/admin/periodic_tasks.py).
"""

import html
import logging

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ... import site_settings as _site_settings_mod
from ...database import get_db
from ...models import SiteSettings
from ...site_settings import get_site_settings
from ...users.auth import require_admin as _require_admin
from ._html import (
    _BASE_CSS,
    _FAVICON,
    _P,
    _PAGE_CSS,
    _RESPONSIVE_CSS,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_SETTINGS_CSS = """
    .flash-banner {
      display: flex; align-items: center; gap: .5rem;
      background: rgba(184,187,38,.12); border: 1px solid rgba(184,187,38,.35); color: #b8bb26;
      border-radius: 10px; padding: .65rem 1rem; margin-bottom: 1.25rem;
      font-size: .82rem; font-weight: 500;
    }
    .status-row { display: flex; gap: .75rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .status-chip {
      display: flex; align-items: center; gap: .55rem;
      background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
      padding: .6rem .9rem;
    }
    .status-chip-label { font-size: .72rem; color: var(--text-2); }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .status-chip-value { font-size: .82rem; font-weight: 600; }

    .settings-section {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.1rem 1.25rem; margin-bottom: 1.25rem;
    }
    .settings-title {
      display: flex; align-items: center; gap: .5rem;
      font-size: .82rem; font-weight: 600; color: var(--text); margin-bottom: .9rem;
    }
    .settings-title .icon { font-size: 1rem; line-height: 1; }
    .settings-hint { font-size: .72rem; color: var(--text-3); margin-top: .5rem; }
    .toggle-row {
      display: flex; align-items: flex-start; gap: .8rem;
      padding: .5rem 0; border-bottom: 1px solid var(--border-sub);
    }
    .toggle-row:last-of-type { border-bottom: none; }
    .toggle-copy { display: flex; flex-direction: column; gap: .1rem; }
    .toggle-label { font-size: .84rem; color: var(--text); font-weight: 500; }
    .toggle-desc { font-size: .72rem; color: var(--text-3); }

    .switch { position: relative; display: inline-block; width: 38px; height: 21px; flex-shrink: 0; margin-top: .1rem; }
    .switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
    .switch-slider {
      position: absolute; inset: 0; background: var(--border-sub); border: 1px solid var(--border);
      border-radius: 999px; transition: background .15s, border-color .15s; pointer-events: none;
    }
    .switch-slider::before {
      content: ""; position: absolute; height: 15px; width: 15px; left: 2px; top: 2px;
      background: var(--text-2); border-radius: 50%; transition: transform .15s, background .15s;
    }
    .switch input:checked + .switch-slider { background: rgba(250,189,47,.22); border-color: var(--accent); }
    .switch input:checked + .switch-slider::before { transform: translateX(17px); background: var(--accent); }
    .switch input:focus-visible + .switch-slider { outline: 2px solid var(--accent); outline-offset: 2px; }

    .settings-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: .5rem .75rem; margin-bottom: .9rem;
    }
    .settings-field { display: flex; flex-direction: column; gap: .3rem; }
    .settings-field label {
      font-size: .72rem; color: var(--text-2); font-weight: 500;
      text-transform: uppercase; letter-spacing: .04em;
    }
    .settings-field input[type=number] {
      background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .35rem .6rem; font-size: .82rem; font-family: inherit;
      width: 100%;
    }
    .settings-field input[type=number]:focus { outline: none; border-color: var(--accent); }
    .settings-field input[type=text] {
      background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .35rem .6rem; font-size: .82rem; font-family: inherit;
      width: 100%;
    }
    .settings-field input[type=text]:focus { outline: none; border-color: var(--accent); }
    .settings-warning {
      font-size: .72rem; color: #fb4934; margin-top: .5rem;
    }
    .settings-save {
      background: var(--accent); border: 1px solid var(--accent); color: var(--bg);
      border-radius: 7px; padding: .5rem 1.3rem; font-size: .82rem; font-weight: 600;
      cursor: pointer; font-family: inherit;
    }
    .settings-save:hover { filter: brightness(1.08); }
"""


def _render_site_settings(ss: SiteSettings, saved: bool = False) -> str:
    def checked(val: bool) -> str:
        return " checked" if val else ""

    def nv(val: int) -> str:
        return html.escape(str(val))

    def sv(val: str) -> str:
        return html.escape(val)

    def toggle(name: str, field_id: str, value: bool, label: str, desc: str) -> str:
        return f"""
        <div class="toggle-row">
          <label class="switch">
            <input type="checkbox" name="{name}" id="{field_id}" value="1"{checked(value)}>
            <span class="switch-slider"></span>
          </label>
          <div class="toggle-copy">
            <span class="toggle-label">{label}</span>
            <span class="toggle-desc">{desc}</span>
          </div>
        </div>"""

    flash = (
        '<div class="flash-banner">&#x2713; Settings saved &mdash; new values take effect immediately.</div>'
        if saved
        else ""
    )
    reg_dot = "#b8bb26" if ss.registration_open else "#fb4934"
    invite_dot = "#fabd2f" if ss.invite_only else "#928374"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Site Settings &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_SETTINGS_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x2699;</div>
      <div class="brand">
        <span class="brand-name">Site Settings</span>
        <span class="brand-sub">xoutaim</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">
    {flash}

    <div class="status-row">
      <div class="status-chip">
        <span class="status-dot" style="background:{reg_dot}"></span>
        <span class="status-chip-label">Registration</span>
        <span class="status-chip-value">{"Open" if ss.registration_open else "Closed"}</span>
      </div>
      <div class="status-chip">
        <span class="status-dot" style="background:{invite_dot}"></span>
        <span class="status-chip-label">Invite only</span>
        <span class="status-chip-value">{"On" if ss.invite_only else "Off"}</span>
      </div>
    </div>

    <form method="post" action="{_P}/settings">
      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x1F6AA;</span>Registration</div>
        {
        toggle(
            "registration_open",
            "reg_open",
            ss.registration_open,
            "Registration open",
            "New accounts can be created at all. Off closes signups completely.",
        )
    }
        {
        toggle(
            "invite_only",
            "invite_only",
            ss.invite_only,
            "Invite only",
            "Require a valid invite code to register (see the Invite Codes page).",
        )
    }
        <p class="settings-hint">
          When <em>invite only</em> is on, <em>registration open</em> must also be on &mdash;
          otherwise registration is closed entirely regardless of invite codes.
        </p>
      </div>

      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x1F30A;</span>Rate limits &amp; flood protection</div>
        <div class="settings-grid">
          <div class="settings-field">
            <label for="rate_lpm">General req / IP / min (soft throttle)</label>
            <input type="number" id="rate_lpm" name="rate_limit_per_minute"
                   value="{nv(ss.rate_limit_per_minute)}" min="1" max="100000" required>
          </div>
          <div class="settings-field">
            <label for="flood_lpm">Flood ban threshold / IP / min</label>
            <input type="number" id="flood_lpm" name="flood_ban_per_minute"
                   value="{nv(ss.flood_ban_per_minute)}" min="1" max="100000" required>
          </div>
          <div class="settings-field">
            <label for="auth_lpm">Auth req / IP / min (login + register)</label>
            <input type="number" id="auth_lpm" name="auth_rate_limit_per_minute"
                   value="{nv(ss.auth_rate_limit_per_minute)}" min="1" max="10000" required>
          </div>
          <div class="settings-field">
            <label for="reg_lph">New accounts / IP / hour</label>
            <input type="number" id="reg_lph" name="register_per_hour_per_ip"
                   value="{nv(ss.register_per_hour_per_ip)}" min="1" max="10000" required>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x23F3;</span>Login backoff</div>
        <div class="settings-grid">
          <div class="settings-field">
            <label for="bo_thresh">Failures per (account, IP) before backoff</label>
            <input type="number" id="bo_thresh" name="login_backoff_threshold"
                   value="{nv(ss.login_backoff_threshold)}" min="1" max="1000" required>
          </div>
          <div class="settings-field">
            <label for="bo_acct">Failures per account (all IPs) before backoff</label>
            <input type="number" id="bo_acct" name="login_backoff_account_threshold"
                   value="{nv(ss.login_backoff_account_threshold)}" min="1" max="10000" required>
          </div>
          <div class="settings-field">
            <label for="bo_min">Backoff duration (minutes)</label>
            <input type="number" id="bo_min" name="login_backoff_minutes"
                   value="{nv(ss.login_backoff_minutes)}" min="1" max="10080" required>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x1F50D;</span>Probe detection &amp; temp bans</div>
        <div class="settings-grid">
          <div class="settings-field">
            <label for="probe_thresh">Unknown paths before temp ban</label>
            <input type="number" id="probe_thresh" name="probe_ban_threshold"
                   value="{nv(ss.probe_ban_threshold)}" min="1" max="1000" required>
          </div>
          <div class="settings-field">
            <label for="probe_win">Probe detection window (minutes)</label>
            <input type="number" id="probe_win" name="probe_window_minutes"
                   value="{nv(ss.probe_window_minutes)}" min="1" max="1440" required>
          </div>
          <div class="settings-field">
            <label for="ban_min">First-offense ban duration (minutes)</label>
            <input type="number" id="ban_min" name="ban_minutes"
                   value="{nv(ss.ban_minutes)}" min="1" max="1440" required>
          </div>
          <div class="settings-field">
            <label for="strike_thresh">Offenses before permanent ban</label>
            <input type="number" id="strike_thresh" name="strike_ban_threshold"
                   value="{nv(ss.strike_ban_threshold)}" min="1" max="100" required>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x1F310;</span>Network &amp; exemptions</div>
        {
        toggle(
            "trust_proxy_headers",
            "trust_proxy",
            ss.trust_proxy_headers,
            "Trust X-Forwarded-For",
            "Only turn this on when there's an actual reverse proxy/CDN in front of this server.",
        )
    }
        <p class="settings-warning">
          &#x26A0; Without a real proxy, that header is entirely client-supplied &mdash;
          turning this on lets anyone spoof their IP to dodge every limit above,
          or get an innocent IP (the proxy's own) banned.
        </p>
        <div class="settings-grid" style="margin-top:.9rem">
          <div class="settings-field" style="grid-column: 1 / -1">
            <label for="exempt_ips">Exempt IPs (comma-separated)</label>
            <input type="text" id="exempt_ips" name="exempt_ips"
                   value="{sv(", ".join(ss.exempt_ips))}" placeholder="127.0.0.1, ::1">
          </div>
        </div>
        <p class="settings-hint">
          These IPs skip rate limiting, probing detection, and bans entirely &mdash;
          reserve this for monitoring or local tooling, never a shared/public IP.
        </p>
      </div>

      <div class="settings-section">
        <div class="settings-title"><span class="icon">&#x23F1;</span>Periodic background tasks</div>
        <p class="settings-hint">
          Episode check, episode history sync, film release check, and strike
          cleanup each have their own enable switch and poll interval on the
          <a href="{_P}/periodic-tasks">Periodic Tasks</a> page.
        </p>
      </div>

      <button class="settings-save" type="submit">Save all settings</button>
    </form>

  </div>

</body>
</html>"""


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def admin_settings(
    saved: bool = Query(default=False),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return _render_site_settings(get_site_settings(db), saved=saved)


@router.post("/settings", include_in_schema=False)
def save_settings(
    registration_open: str | None = Form(default=None),
    invite_only: str | None = Form(default=None),
    rate_limit_per_minute: int = Form(...),
    flood_ban_per_minute: int = Form(...),
    auth_rate_limit_per_minute: int = Form(...),
    register_per_hour_per_ip: int = Form(...),
    login_backoff_threshold: int = Form(...),
    login_backoff_account_threshold: int = Form(...),
    login_backoff_minutes: int = Form(...),
    probe_ban_threshold: int = Form(...),
    probe_window_minutes: int = Form(...),
    ban_minutes: int = Form(...),
    strike_ban_threshold: int = Form(...),
    trust_proxy_headers: str | None = Form(default=None),
    exempt_ips: str = Form(default=""),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    ss = get_site_settings(db)
    ss.registration_open = registration_open == "1"
    ss.invite_only = invite_only == "1"
    ss.rate_limit_per_minute = rate_limit_per_minute
    ss.flood_ban_per_minute = flood_ban_per_minute
    ss.auth_rate_limit_per_minute = auth_rate_limit_per_minute
    ss.register_per_hour_per_ip = register_per_hour_per_ip
    ss.login_backoff_threshold = login_backoff_threshold
    ss.login_backoff_account_threshold = login_backoff_account_threshold
    ss.login_backoff_minutes = login_backoff_minutes
    ss.probe_ban_threshold = probe_ban_threshold
    ss.probe_window_minutes = probe_window_minutes
    ss.ban_minutes = ban_minutes
    ss.strike_ban_threshold = strike_ban_threshold
    ss.trust_proxy_headers = trust_proxy_headers == "1"
    ss.exempt_ips = [ip.strip() for ip in exempt_ips.split(",") if ip.strip()]
    db.commit()
    _site_settings_mod.invalidate()
    _log.info(
        "admin=%s updated site settings (invite_only=%s registration_open=%s)",
        admin_user,
        ss.invite_only,
        ss.registration_open,
    )
    return RedirectResponse(f"{_P}/settings?saved=1", status_code=303)
