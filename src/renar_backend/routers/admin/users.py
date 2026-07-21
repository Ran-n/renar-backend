#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/21 09:51:03.543243

Admin user-management: list, detail, library drill-down, and all user
action endpoints (ban/unban, premium, verify, edit, password, delete).
"""

import html
import logging
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import (
    Comment,
    EndpointStat,
    EpisodeWatch,
    LibraryEntry,
    LoginEvent,
    MediaType,
    RequestDay,
    Title,
    User,
    WatchEvent,
    WatchStatus,
    utcnow,
)
from ...users import accounts
from ...users import security as _security
from ...users.auth import hash_password
from ...users.auth import require_admin as _require_admin
from ._html import (
    _BASE_CSS,
    _CHART_DAYS,
    _CHART_TIP,
    _DETAIL_CSS,
    _EMAIL_RE,
    _FAVICON,
    _P,
    _PAGE_CSS,
    _RESPONSIVE_CSS,
    _daily_counts,
    _daily_from_map,
    _endpoint_item,
    _fmt_ts,
    _render_daily_chart,
    _render_endpoint_bars,
    _render_hbars,
    _stat_tile,
    _usage_page,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_USERS_PAGE_SIZE = 200

# Sentinel for a permanent grant: is_premium checks premium_until > utcnow(),
# there's no separate boolean, so "forever" is just a date past any realistic
# lapse. datetime.max itself doesn't round-trip through every DB driver.
PREMIUM_FOREVER = datetime(9999, 1, 1, tzinfo=UTC)


def _premium_pills(user: User) -> str:
    """Stored premium/verified state (shown even while lapsed — the admin
    needs to see what is on the account, not what currently renders)."""
    pills = ""
    if user.verified:
        pills += ' <span class="pill" style="margin-left:.4rem">verified</span>'
    elif user.is_premium:
        pills += ' <span class="pill" style="margin-left:.4rem">premium</span>'
    if user.verification_requested:
        pills += ' <span class="pill" style="margin-left:.4rem">verification requested</span>'
    # email_confirmed backs /stats/ranking's percentile filter (see
    # routers/stats.py._compute_ranking) — surfaced here so an admin can see
    # at a glance why an account isn't showing up on the leaderboard.
    if user.email_confirmed:
        pills += ' <span class="pill" style="margin-left:.4rem">email confirmed</span>'
    elif user.email_confirmation_grandfathered:
        # predates the feature — exempt from the login-gate block and the
        # cleanup deletion, but still correctly absent from the ranking pill
        # above until it actually confirms (see migration ffffe2b24717).
        pills += ' <span class="pill" style="margin-left:.4rem">grandfathered</span>'
    return pills


def _render_premium_actions(user: User) -> str:
    """Grant/revoke premium time and approve/revoke the verified badge."""
    uid = user.id
    name_esc = html.escape(user.username)
    if user.is_premium and user.premium_until >= PREMIUM_FOREVER:
        premium_state = "Premium active forever"
    elif user.is_premium:
        premium_state = f"Premium active until {_fmt_ts(user.premium_until)}"
    elif user.premium_until:
        premium_state = f"Premium lapsed {_fmt_ts(user.premium_until)}"
    else:
        premium_state = "No premium"
    revoke = ""
    if user.premium_until:
        revoke = (
            f'<form method="post" action="{_P}/users/{uid}/premium/revoke" style="display:contents"'
            f" onsubmit=\"return confirm('Revoke premium for [{name_esc}]?')\">"
            f'<button class="btn-sm" type="submit">Revoke premium</button></form>'
        )
    if user.verified:
        verify_action = (
            f'<form method="post" action="{_P}/users/{uid}/unverify" style="display:contents"'
            f" onsubmit=\"return confirm('Revoke verified badge for [{name_esc}]?')\">"
            f'<button class="btn-sm" type="submit">Revoke verified</button></form>'
        )
    elif user.verification_requested:
        verify_action = (
            f'<form method="post" action="{_P}/users/{uid}/verify" style="display:contents">'
            f'<button class="btn-sm btn-good" type="submit">Approve verification</button></form>'
            f'<form method="post" action="{_P}/users/{uid}/verify/deny" style="display:contents">'
            f'<button class="btn-sm" type="submit">Deny request</button></form>'
        )
    else:
        verify_action = (
            f'<form method="post" action="{_P}/users/{uid}/verify" style="display:contents">'
            f'<button class="btn-sm btn-good" type="submit">Grant verified</button></form>'
        )
    return f"""
    <div class="actions-card">
      <div class="actions-title">Premium &amp; verification</div>
      <div class="action-row">
        <label>Status</label>
        <span style="font-size:.82rem;color:var(--text-2)">{premium_state}</span>
        {revoke}
      </div>
      <form class="action-row" method="post" action="{_P}/users/{uid}/premium">
        <label>Grant days</label>
        <input class="action-input" type="number" name="days" min="1" placeholder="e.g. 30" required>
        <button class="btn-save" type="submit">Grant</button>
      </form>
      <form class="action-row" method="post" action="{_P}/users/{uid}/premium">
        <label>Until date</label>
        <input class="action-input" type="date" name="until_date" required>
        <button class="btn-save" type="submit">Set</button>
      </form>
      <form class="action-row" method="post" action="{_P}/users/{uid}/premium"
            onsubmit="return confirm('Grant permanent premium to [{name_esc}]?')">
        <label>Forever</label>
        <input type="hidden" name="forever" value="1">
        <button class="btn-save" type="submit">Grant forever</button>
      </form>
      <div class="action-sep"></div>
      <div class="action-row">
        <label>Verified badge</label>
        {verify_action}
      </div>
    </div>"""


def _render_account_actions(user: User) -> str:
    """Inline admin controls: edit username/email, set a new password, ban/delete."""
    uid = user.id
    name_esc = html.escape(user.username)
    if user.banned:
        ban_action = (
            f'<form method="post" action="{_P}/users/{uid}/unban" style="display:contents">'
            f'<button class="btn-sm" type="submit">Unban</button></form>'
        )
    else:
        ban_action = (
            f'<form method="post" action="{_P}/users/{uid}/ban" style="display:contents"'
            f" onsubmit=\"return confirm('Ban [{name_esc}]? They will be signed out and unable to log back in.')\">"
            f'<button class="btn-sm" type="submit">Ban</button></form>'
        )
    return f"""
    <div class="actions-card">
      <div class="actions-title">Account actions</div>
      <form class="action-row" method="post" action="{_P}/users/{uid}/edit">
        <label>Username</label>
        <input class="action-input" type="text" name="username" value="{html.escape(user.username, quote=True)}"
               maxlength="50" required>
        <button class="btn-save" type="submit">Save</button>
      </form>
      <form class="action-row" method="post" action="{_P}/users/{uid}/edit">
        <label>Email</label>
        <input class="action-input" type="email" name="email" value="{html.escape(user.email, quote=True)}"
               maxlength="255" required>
        <button class="btn-save" type="submit">Save</button>
      </form>
      <form class="action-row" method="post" action="{_P}/users/{uid}/password"
            onsubmit="return confirm('Set a new password for [{name_esc}]?')">
        <label>New password</label>
        <input class="action-input" type="password" name="new_password" placeholder="at least 8 characters"
               minlength="8" maxlength="72" required>
        <button class="btn-save" type="submit">Set password</button>
      </form>
      <div class="action-sep"></div>
      <div class="action-danger">
        <form method="post" action="{_P}/users/{uid}/reset-login-limit" style="display:contents">
          <button class="btn-sm" type="submit">Reset sign-in rate limit</button>
        </form>
        <form method="post" action="{_P}/users/{uid}/reset-onboarding" style="display:contents">
          <button class="btn-sm" type="submit">Reset onboarding</button>
        </form>
        {ban_action}
        <form method="post" action="{_P}/users/{uid}/delete" style="display:contents"
              onsubmit="return confirm('Permanently delete [{name_esc}] and all their data?')">
          <button class="btn-sm btn-purge" type="submit">Delete account</button>
        </form>
      </div>
    </div>"""


def _render_user_detail(
    user: User,
    login_ts: list,
    watch_ts: list,
    comment_ts: list,
    add_ts: list,
    by_type: list[tuple],
    by_status: list[tuple],
    favorites: int,
    episodes_watched: int,
    request_total: int,
    request_series: list,
    endpoints_href: str,
) -> str:
    name_esc = html.escape(user.username)
    if user.avatar:
        avatar = f'<img class="detail-avatar" src="{html.escape(user.avatar)}" alt="">'
    else:
        avatar = f'<span class="detail-avatar-fallback">{name_esc[:1].upper()}</span>'
    banned_badge = '<span class="pill">banned</span>' if user.banned else ""
    banned_badge += _premium_pills(user)

    tiles = "".join([
        _stat_tile("Logins", len(login_ts)),
        _stat_tile("API requests", request_total),
        _stat_tile("Library items", len(add_ts)),
        _stat_tile("Comments", len(comment_ts)),
        _stat_tile("Favorites", favorites),
        _stat_tile("Episodes watched", episodes_watched),
    ])

    requests_footer = f'<a class="ep-more" href="{endpoints_href}">View endpoint breakdown &rarr;</a>'
    charts = "".join([
        _render_daily_chart("Requests per day", request_series, "requests", footer=requests_footer),
        _render_daily_chart("Connections per day", _daily_counts(login_ts), "logins"),
        _render_daily_chart("Watches per day", _daily_counts(watch_ts), "watches"),
        _render_daily_chart("Comments per day", _daily_counts(comment_ts), "comments"),
        _render_daily_chart("Library adds per day", _daily_counts(add_ts), "added"),
        _render_hbars("Library by type", by_type, "items", cap=True),
        _render_hbars("Library by status", by_status, "items", cap=True),
    ])
    actions = _render_premium_actions(user) + _render_account_actions(user)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name_esc} &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_DETAIL_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F464;</div>
      <div class="brand">
        <span class="brand-name">User Detail</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}/users">Users</a>
  </header>

  <div class="page">
    <a class="back-link" href="{_P}/users">&#8592; Back to users</a>

    <div class="detail-head">
      {avatar}
      <div class="detail-id">
        <div class="detail-name">{name_esc}{banned_badge}</div>
        <div class="detail-email">{html.escape(user.email)}</div>
        <div class="detail-meta">
          <div>Joined {_fmt_ts(user.created_at)}</div>
          <div>Last login {_fmt_ts(max(login_ts, default=None))}</div>
          <div>Last active {_fmt_ts(user.last_active_at)}</div>
        </div>
      </div>
    </div>

    {actions}

    <div class="stats">{tiles}</div>

    <div class="charts-grid">{charts}</div>
  </div>
  {_CHART_TIP}
</body>
</html>"""


def _render_users(
    users: list[User],
    item_counts: dict[int, int],
    comment_counts: dict[int, int],
    login_counts: dict[int, int],
    last_logins: dict,
    request_counts: dict[int, int],
    totals: dict[str, int],
    page: int = 1,
    total_pages: int = 1,
) -> str:
    rows = ""
    for u in sorted(users, key=lambda u: u.username.lower()):
        name_esc = html.escape(u.username)
        if u.avatar:
            avatar = f'<img class="avatar" src="{html.escape(u.avatar)}" alt="">'
        else:
            avatar = f'<span class="avatar-fallback">{name_esc[:1].upper()}</span>'
        name_link = f'<a class="td-link" href="{_P}/users/{u.id}">{name_esc}</a>'
        badge = ""
        if u.banned:
            ban_action = f"""<form method="post" action="{_P}/users/{u.id}/unban" style="display:contents">
              <button class="btn-sm" type="submit">Unban</button>
            </form>"""
            badge = ' <span class="pill" style="margin-left:.4rem">banned</span>'
        else:
            ban_action = f"""<form method="post" action="{_P}/users/{u.id}/ban"
                  onsubmit="return confirm('Ban [{name_esc}]? They will be signed out and unable to log back in.')"
                  style="display:contents">
              <button class="btn-sm" type="submit">Ban</button>
            </form>"""
        badge += _premium_pills(u)
        n_comments = comment_counts.get(u.id, 0)
        comments_cell = str(n_comments)
        if n_comments:
            comments_cell = f'<a class="td-link" href="{_P}/comments?user_id={u.id}">{n_comments}</a>'
        rows += f"""
        <tr>
          <td class="td-label"><div class="user-cell">{avatar}<span>{name_link}{badge}</span></div></td>
          <td class="td-email">{html.escape(u.email)}</td>
          <td class="td-count">{item_counts.get(u.id, 0)}</td>
          <td class="td-count">{comments_cell}</td>
          <td class="td-count">{login_counts.get(u.id, 0)}</td>
          <td class="td-count">{request_counts.get(u.id, 0)}</td>
          <td class="td-ts">{_fmt_ts(u.created_at)}</td>
          <td class="td-ts">{_fmt_ts(last_logins.get(u.id))}</td>
          <td class="td-ts">{_fmt_ts(u.last_active_at)}</td>
          <td><div class="td-actions">
            {ban_action}
            <form method="post" action="{_P}/users/{u.id}/delete"
                  onsubmit="return confirm('Permanently delete [{name_esc}] and all their data?')"
                  style="display:contents">
              <button class="btn-sm btn-purge" type="submit">Delete</button>
            </form>
          </div></td>
        </tr>"""

    empty_row = '<tr><td colspan="10" class="empty">No users</td></tr>' if not rows else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>User Manager &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F465;</div>
      <div class="brand">
        <span class="brand-name">User Manager</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">

    <div class="stats">
      <div class="stat">
        <div class="stat-label">Users</div>
        <div class="stat-value" id="stat-users">{totals["users"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Media Items</div>
        <div class="stat-value" id="stat-items">{totals["items"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Episode Watches</div>
        <div class="stat-value" id="stat-watches">{totals["watches"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Comments</div>
        <div class="stat-value" id="stat-comments">{totals["comments"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Active Today</div>
        <div class="stat-value" id="stat-active-today">{totals["active_today"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Active (7d)</div>
        <div class="stat-value" id="stat-active-7d">{totals["active_7d"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Hero on</div>
        <div class="stat-value" id="stat-home-hero">{totals["home_hero_on"]}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Opens on Home</div>
        <div class="stat-value" id="stat-home-launch">{totals["home_on_launch_on"]}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <button class="btn-refresh" id="refresh-btn" type="button" onclick="refreshTable()" title="Refresh users">
          <span class="icon-refresh">&#x21bb;</span>
        </button>
        <h2 class="card-title">Users</h2>
        <span class="pill" id="pill-users">{totals["users"]} registered</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th data-col="0" data-type="text">User</th>
            <th data-col="1" data-type="text">Email</th>
            <th data-col="2" data-type="num">Items</th>
            <th data-col="3" data-type="num">Comments</th>
            <th data-col="4" data-type="num">Logins</th>
            <th data-col="5" data-type="num">Requests</th>
            <th data-col="6" data-type="text">Joined</th>
            <th data-col="7" data-type="text">Last login</th>
            <th data-col="8" data-type="text">Last active</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="users-tbody">
          {rows}{empty_row}
        </tbody>
      </table>
      </div>
    </div>

  </div>

  <script>
    async function refreshTable() {{
      const btn = document.getElementById('refresh-btn');
      btn.disabled = true;
      btn.classList.add('loading');
      try {{
        const res = await fetch(window.location.href, {{credentials: 'include'}});
        if (!res.ok) throw new Error(res.status);
        const text = await res.text();
        const doc = new DOMParser().parseFromString(text, 'text/html');
        const swap = (id) => {{
          const src = doc.getElementById(id);
          const dst = document.getElementById(id);
          if (src && dst) dst.innerHTML = src.innerHTML;
        }};
        swap('users-tbody');
        swap('stat-users');
        swap('stat-items');
        swap('stat-watches');
        swap('stat-comments');
        swap('stat-active-today');
        swap('stat-active-7d');
        swap('pill-users');
        initSort();
      }} catch (e) {{
        console.error('Refresh failed:', e);
      }} finally {{
        btn.disabled = false;
        btn.classList.remove('loading');
      }}
    }}

    let _sortCol = null, _sortAsc = true;

    function initSort() {{
      const ths = document.querySelectorAll('th[data-col]');
      const tbody = document.getElementById('users-tbody');
      const origOrder = Array.from(tbody.querySelectorAll('tr'));

      function applySort(col, type, asc) {{
        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {{
          const av = a.cells[col] ? a.cells[col].textContent.trim().replace(/\\s+/g, ' ') : '';
          const bv = b.cells[col] ? b.cells[col].textContent.trim().replace(/\\s+/g, ' ') : '';
          let cmp = type === 'num' ? (+av || 0) - (+bv || 0)
                                   : av.localeCompare(bv, undefined, {{sensitivity: 'base', numeric: true}});
          return asc ? cmp : -cmp;
        }});
        rows.forEach(r => tbody.appendChild(r));
      }}

      function clearSort() {{
        _sortCol = null;
        ths.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
        origOrder.forEach(r => tbody.appendChild(r));
      }}

      ths.forEach(th => {{
        th.onclick = null;
        th.oncontextmenu = null;
        th.addEventListener('click', () => {{
          const col = +th.dataset.col;
          const type = th.dataset.type;
          if (_sortCol === col) {{ _sortAsc = !_sortAsc; }} else {{ _sortCol = col; _sortAsc = true; }}
          ths.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
          th.classList.add(_sortAsc ? 'sort-asc' : 'sort-desc');
          applySort(col, type, _sortAsc);
        }});
        th.addEventListener('contextmenu', e => {{
          if (_sortCol === +th.dataset.col) {{ e.preventDefault(); clearSort(); }}
        }});
      }});
    }}

    initSort();
  </script>
  {_pagination_nav(page, total_pages)}
</body>
</html>"""


def _pagination_nav(page: int, total_pages: int) -> str:
    """Simple prev/next page controls; only rendered when there is more than one page."""
    if total_pages <= 1:
        return ""
    prev_link = (
        f'<a class="admin-pill" href="{_P}/users?page={page - 1}">&laquo; Prev</a>'
        if page > 1
        else '<span class="admin-pill" style="opacity:.4">&laquo; Prev</span>'
    )
    next_link = (
        f'<a class="admin-pill" href="{_P}/users?page={page + 1}">Next &raquo;</a>'
        if page < total_pages
        else '<span class="admin-pill" style="opacity:.4">Next &raquo;</span>'
    )
    return (
        f'<div style="display:flex;gap:.5rem;justify-content:center;padding:1rem 0">'
        f"{prev_link} <span>Page {page} / {total_pages}</span> {next_link}</div>"
    )


def _render_user_library(user: User, entries: list[LibraryEntry], filter_label: str) -> str:
    rows = ""
    for e in entries:
        rating = e.rating if e.rating is not None else "&mdash;"
        rows += f"""
        <tr>
          <td class="td-label">{html.escape(e.title)}</td>
          <td class="td-count">{e.year or "&mdash;"}</td>
          <td><span class="type-pill">{html.escape(e.media_type.value.replace("_", " "))}</span></td>
          <td class="td-email">{html.escape(e.status.value.replace("_", " "))}</td>
          <td class="td-count">{rating}</td>
        </tr>"""
    empty_row = '<tr><td colspan="5" class="empty">No titles</td></tr>' if not rows else ""
    name_esc = html.escape(user.username)
    inner = f"""
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">{name_esc} &middot; {html.escape(filter_label)}</h2>
        <span class="pill">{len(entries)} titles</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr><th>Title</th><th>Year</th><th>Type</th><th>Status</th><th>Rating</th></tr>
        </thead>
        <tbody>{rows}{empty_row}</tbody>
      </table>
      </div>
    </div>"""
    return _usage_page(f"{user.username} · library", "&#x1F4DA;", f"{_P}/users/{user.id}", "Back to user", inner)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
def list_users(
    page: int = Query(default=1, ge=1),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    total_users = db.query(func.count(User.id)).scalar() or 0
    offset = (page - 1) * _USERS_PAGE_SIZE
    users = db.query(User).order_by(User.username).offset(offset).limit(_USERS_PAGE_SIZE).all()
    # Aggregate lookups scoped to the current page only — avoids full-table
    # GROUP BY scans on every render when the user base is large.
    page_user_ids = [u.id for u in users]
    item_counts = (
        dict(
            db.query(LibraryEntry.user_id, func.count())
            .filter(LibraryEntry.user_id.in_(page_user_ids))
            .group_by(LibraryEntry.user_id)
            .all()
        )
        if page_user_ids
        else {}
    )
    comment_counts = (
        dict(
            db.query(Comment.user_id, func.count())
            .filter(Comment.user_id.in_(page_user_ids))
            .group_by(Comment.user_id)
            .all()
        )
        if page_user_ids
        else {}
    )
    login_counts = (
        dict(
            db.query(LoginEvent.user_id, func.count())
            .filter(LoginEvent.user_id.in_(page_user_ids))
            .group_by(LoginEvent.user_id)
            .all()
        )
        if page_user_ids
        else {}
    )
    last_logins = (
        dict(
            db.query(LoginEvent.user_id, func.max(LoginEvent.created_at))
            .filter(LoginEvent.user_id.in_(page_user_ids))
            .group_by(LoginEvent.user_id)
            .all()
        )
        if page_user_ids
        else {}
    )
    request_counts = (
        {
            uid: int(total)
            for uid, total in db.query(RequestDay.user_id, func.sum(RequestDay.count))
            .filter(RequestDay.user_id.in_(page_user_ids))
            .group_by(RequestDay.user_id)
            .all()
        }
        if page_user_ids
        else {}
    )
    now = utcnow()
    totals = {
        "users": total_users,
        "items": db.query(func.count(LibraryEntry.id)).scalar() or 0,
        "watches": db.query(func.count(EpisodeWatch.id)).scalar() or 0,
        "comments": db.query(func.count(Comment.id)).scalar() or 0,
        "active_today": db.query(func.count(User.id)).filter(User.last_active_at >= now - timedelta(days=1)).scalar()
        or 0,
        "active_7d": db.query(func.count(User.id)).filter(User.last_active_at >= now - timedelta(days=7)).scalar() or 0,
        "home_hero_on": db.query(func.count(User.id)).filter(User.home_hero_enabled.is_(True)).scalar() or 0,
        "home_on_launch_on": db.query(func.count(User.id)).filter(User.home_on_launch.is_(True)).scalar() or 0,
    }
    total_pages = max(1, -(-total_users // _USERS_PAGE_SIZE))  # ceiling division
    return _render_users(
        users,
        item_counts,
        comment_counts,
        login_counts,
        last_logins,
        request_counts,
        totals,
        page=page,
        total_pages=total_pages,
    )


@router.get("/users/{user_id}", response_class=HTMLResponse, include_in_schema=False)
def user_detail(
    user_id: int,
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    login_ts = [r[0] for r in db.query(LoginEvent.created_at).filter(LoginEvent.user_id == user_id)]
    comment_ts = [r[0] for r in db.query(Comment.created_at).filter(Comment.user_id == user_id)]
    add_ts = [r[0] for r in db.query(LibraryEntry.created_at).filter(LibraryEntry.user_id == user_id)]
    watch_ts = [
        r[0]
        for r in db.query(WatchEvent.watched_at)
        .join(LibraryEntry, WatchEvent.media_item_id == LibraryEntry.id)
        .filter(LibraryEntry.user_id == user_id)
    ]

    type_counts = dict(
        db.query(Title.media_type, func.count())
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(LibraryEntry.user_id == user_id)
        .group_by(Title.media_type)
        .all()
    )
    status_counts = dict(
        db.query(LibraryEntry.status, func.count())
        .filter(LibraryEntry.user_id == user_id)
        .group_by(LibraryEntry.status)
        .all()
    )
    # Fixed order, only rows with data — labels humanized (tv_show -> "tv show").
    # Each row links to the drill-down that lists the actual titles in that bucket.
    by_type = [
        (mt.value.replace("_", " "), type_counts[mt], f"{_P}/users/{user_id}/library?media_type={mt.value}")
        for mt in MediaType
        if type_counts.get(mt)
    ]
    by_status = [
        (st.value.replace("_", " "), status_counts[st], f"{_P}/users/{user_id}/library?status={st.value}")
        for st in WatchStatus
        if status_counts.get(st)
    ]

    favorites = (
        db.query(func.count(LibraryEntry.id))
        .filter(LibraryEntry.user_id == user_id, LibraryEntry.is_favorite.is_(True))
        .scalar()
        or 0
    )
    episodes_watched = (
        db.query(func.count(EpisodeWatch.id))
        .join(LibraryEntry, EpisodeWatch.media_item_id == LibraryEntry.id)
        .filter(LibraryEntry.user_id == user_id)
        .scalar()
        or 0
    )

    # Requests-per-day time-series for this user (last 30 days) + all-time total.
    since = utcnow().date() - timedelta(days=_CHART_DAYS - 1)
    request_map = dict(
        db.query(RequestDay.day, RequestDay.count).filter(RequestDay.user_id == user_id, RequestDay.day >= since).all()
    )
    request_series = _daily_from_map(request_map)
    request_total = int(db.query(func.sum(RequestDay.count)).filter(RequestDay.user_id == user_id).scalar() or 0)

    return _render_user_detail(
        user,
        login_ts,
        watch_ts,
        comment_ts,
        add_ts,
        by_type,
        by_status,
        favorites,
        episodes_watched,
        request_total,
        request_series,
        f"{_P}/users/{user_id}/endpoints",
    )


@router.get("/users/{user_id}/endpoints", response_class=HTMLResponse, include_in_schema=False)
def user_endpoints(
    user_id: int,
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rows = (
        db.query(EndpointStat.method, EndpointStat.path, func.sum(EndpointStat.count))
        .filter(EndpointStat.user_id == user_id)
        .group_by(EndpointStat.method, EndpointStat.path)
        .all()
    )
    rows = sorted(rows, key=lambda r: r[2] or 0, reverse=True)
    items = [_endpoint_item(m, p, t) for m, p, t in rows]
    inner = (
        f'<div class="detail-head"><div class="detail-id">'
        f'<div class="detail-name">{html.escape(user.username)}</div>'
        f'<div class="detail-meta">Full requests-by-endpoint breakdown</div>'
        f"</div></div>{_render_endpoint_bars(items, title='Requests by endpoint')}"
    )
    return _usage_page(f"{user.username} · endpoints", "&#x1F517;", f"{_P}/users/{user_id}", "Back to user", inner)


@router.get("/users/{user_id}/library", response_class=HTMLResponse, include_in_schema=False)
def user_library(
    user_id: int,
    media_type: MediaType | None = Query(default=None),
    status: WatchStatus | None = Query(default=None),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    query = (
        db.query(LibraryEntry).join(Title, LibraryEntry.title_id == Title.id).filter(LibraryEntry.user_id == user_id)
    )
    if media_type is not None:
        query = query.filter(Title.media_type == media_type)
        label = media_type.value.replace("_", " ")
    elif status is not None:
        query = query.filter(LibraryEntry.status == status)
        label = status.value.replace("_", " ")
    else:
        label = "all titles"
    entries = query.order_by(Title.title).all()
    return _render_user_library(user, entries, label)


@router.post("/users/{user_id}/ban", include_in_schema=False)
def ban_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.banned = True
    user.ban_reason = f"banned by admin={admin_user}"
    db.commit()
    _log.info("admin=%s banned user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users", status_code=303)


@router.post("/users/{user_id}/unban", include_in_schema=False)
def unban_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.banned = False
    user.ban_reason = None
    db.commit()
    _log.info("admin=%s unbanned user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users", status_code=303)


@router.post("/users/{user_id}/premium", include_in_schema=False)
def grant_premium(
    user_id: int,
    days: int | None = Form(None),
    until_date: date | None = Form(None),
    forever: bool = Form(False),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if forever:
        user.premium_until = PREMIUM_FOREVER
    elif until_date is not None:
        new_until = datetime.combine(until_date, time.min, tzinfo=UTC)
        if new_until <= utcnow():
            raise HTTPException(status_code=422, detail="until_date must be in the future")
        user.premium_until = new_until
    elif days is not None:
        if days < 1:
            raise HTTPException(status_code=422, detail="days must be at least 1")
        # extend from whichever is later: an active subscription keeps its
        # remaining time, a lapsed one restarts from now
        base = user.premium_until if user.is_premium else utcnow()
        user.premium_until = base + timedelta(days=days)
    else:
        raise HTTPException(status_code=422, detail="one of days, until_date, forever is required")

    db.commit()
    _log.info(
        "admin=%s granted premium to user id=%s username=%s (until %s)",
        admin_user,
        user_id,
        user.username,
        user.premium_until.isoformat(),
    )
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/premium/revoke", include_in_schema=False)
def revoke_premium(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.premium_until = None
    db.commit()
    _log.info("admin=%s revoked premium for user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/verify", include_in_schema=False)
def verify_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.verified = True
    user.verification_requested = False
    db.commit()
    _log.info("admin=%s verified user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/unverify", include_in_schema=False)
def unverify_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.verified = False
    user.verification_requested = False
    db.commit()
    _log.info("admin=%s unverified user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/verify/deny", include_in_schema=False)
def deny_verification(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.verification_requested = False
    db.commit()
    _log.info("admin=%s denied verification request for user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/edit", include_in_schema=False)
def edit_user(
    user_id: int,
    username: str | None = Form(default=None),
    email: str | None = Form(default=None),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if username and username != user.username:
        if db.query(User).filter(User.username == username, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = username
    if email and email != user.email:
        if not _EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Invalid email address")
        if db.query(User).filter(User.email == email, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Email already taken")
        user.email = email
    db.commit()
    _log.info("admin=%s edited user id=%s (username/email)", admin_user, user_id)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/password", include_in_schema=False)
def set_user_password(
    user_id: int,
    new_password: str = Form(...),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # bcrypt refuses >72 bytes; mirror the registration floor of 8.
    if not (8 <= len(new_password) <= 72) or len(new_password.encode()) > 72:
        raise HTTPException(status_code=422, detail="Password must be 8-72 characters")
    user.password_hash = hash_password(new_password)
    db.commit()
    _log.info("admin=%s reset password for user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/reset-login-limit", include_in_schema=False)
def reset_user_login_limit(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _security.reset_login_backoff(user.username)
    _log.info("admin=%s reset login rate limit for user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/reset-onboarding", include_in_schema=False)
def reset_user_onboarding(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.has_seen_welcome = False
    db.commit()
    _log.info("admin=%s reset onboarding for user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/delete", include_in_schema=False)
def delete_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    username = user.username
    accounts.delete_account(user, db)
    _log.info("admin=%s deleted user id=%s username=%s", admin_user, user_id, username)
    return RedirectResponse(f"{_P}/users", status_code=303)
