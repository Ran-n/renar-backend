#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/18 00:26:58.864620

Admin invite-codes page: list, generate, revoke, restore, and delete
registration invite codes.
"""

import html
import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from ...database import get_db
from ...models import InviteCode, utcnow
from ...users.auth import require_admin as _require_admin
from ._html import (
    _BASE_CSS,
    _FAVICON,
    _P,
    _PAGE_CSS,
    _RESPONSIVE_CSS,
    _fmt_ts,
    _stat_tile,
)
from .settings import _SETTINGS_CSS

router = APIRouter()
_log = logging.getLogger(__name__)

_INVITES_CSS = """
    .status-pill {
      display: inline-flex; align-items: center; gap: .3rem;
      font-size: .68rem; font-weight: 600; letter-spacing: .02em;
      border-radius: 9999px; padding: 2px 9px; white-space: nowrap;
    }
    /* Two pills (a code both time-expired and use-exhausted) sit side by
       side in the same cell, no extra row height. */
    .status-pills { display: inline-flex; align-items: center; gap: .35rem; flex-wrap: nowrap; }
    .code-cell { display: flex; align-items: center; gap: .5rem; font-family: monospace; }
    .btn-copy {
      background: transparent; border: 1px solid var(--border); color: var(--text-3);
      border-radius: 6px; padding: 1px 8px; font-size: .68rem; font-family: inherit;
    }
    .btn-copy:hover { color: var(--text-2); border-color: var(--text-3); }
    .uses-cell { display: flex; align-items: center; gap: .5rem; }
    .uses-track { background: var(--border-sub); border-radius: 5px; height: 6px; width: 60px; overflow: hidden; }
    .uses-fill { height: 100%; border-radius: 5px; }

    /* Generate-invite card */
    .gen-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 1.5rem; margin-bottom: 1.25rem;
    }
    .gen-head { display: flex; align-items: flex-start; gap: .9rem; margin-bottom: 1.4rem; }
    .gen-icon {
      width: 42px; height: 42px; border-radius: 11px; flex-shrink: 0;
      background: rgba(250,189,47,.14); color: var(--accent);
      display: flex; align-items: center; justify-content: center;
    }
    .gen-icon svg { width: 22px; height: 22px; }
    .gen-title { font-size: 1rem; font-weight: 700; color: var(--text); letter-spacing: -.01em; }
    .gen-sub { font-size: .78rem; color: var(--text-2); margin-top: .15rem; line-height: 1.4; }

    .gen-field { margin-bottom: 1.1rem; }
    .gen-label {
      display: block; font-size: .7rem; font-weight: 600; color: var(--text-2);
      text-transform: uppercase; letter-spacing: .05em; margin-bottom: .55rem;
    }
    .chip-group { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
    .chip {
      background: var(--bg); border: 1px solid var(--border); color: var(--text-2);
      border-radius: 9999px; padding: .4rem 1rem; font-size: .8rem; font-weight: 500;
      font-family: inherit; cursor: pointer; transition: all .12s;
    }
    .chip:hover { border-color: var(--text-3); color: var(--text); }
    .chip.active {
      background: rgba(250,189,47,.16); border-color: var(--accent); color: var(--accent); font-weight: 600;
    }
    .gen-custom-input {
      background: var(--bg); border: 1px solid var(--accent); color: var(--text);
      border-radius: 8px; padding: .45rem .7rem; font-size: .85rem; font-family: inherit;
      margin-top: .6rem; width: 100%; max-width: 260px;
    }
    .gen-custom-input:focus { outline: none; box-shadow: 0 0 0 2px rgba(250,189,47,.25); }
    .gen-custom-input[hidden] { display: none; }

    .gen-submit {
      display: inline-flex; align-items: center; gap: .5rem;
      background: var(--accent); border: 1px solid var(--accent); color: var(--bg);
      border-radius: 9px; padding: .6rem 1.4rem; font-size: .85rem; font-weight: 700;
      font-family: inherit; cursor: pointer; margin-top: .3rem;
    }
    .gen-submit:hover { filter: brightness(1.08); }
    .gen-submit svg { width: 16px; height: 16px; }

    .just-generated {
      display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
      background: rgba(184,187,38,.1); border: 1px solid rgba(184,187,38,.35);
      border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 1.25rem;
    }
    .just-generated-label {
      font-size: .72rem; color: #b8bb26; font-weight: 600;
      text-transform: uppercase; letter-spacing: .05em;
    }
    .just-generated-code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 1.15rem; font-weight: 600; color: var(--text); letter-spacing: .02em;
    }
    .just-generated { transition: opacity .4s ease; }

    /* Search + status filter toolbar above the table */
    .invites-toolbar {
      display: flex; flex-wrap: wrap; align-items: center; gap: .6rem;
      padding: 0 1.25rem 1rem;
    }
    .invites-search {
      background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 8px; padding: .45rem .7rem; font-size: .85rem; font-family: inherit;
      min-width: 220px; flex: 1 1 220px; max-width: 320px;
    }
    .invites-search:focus { outline: none; border-color: var(--accent); }
    .filter-group { display: flex; flex-wrap: wrap; gap: .5rem; }

    /* Restore-expiry per-row popover: <summary> gets a native disclosure
       marker by default (a triangle) — strip it so it reads the same as
       the plain <button> "Restore" used for revoked codes. */
    .restore-expiry { position: relative; display: inline-block; }
    .restore-expiry summary {
      list-style: none; cursor: pointer;
    }
    .restore-expiry summary::-webkit-details-marker { display: none; }
    .restore-expiry summary::marker { content: ""; }
    .restore-expiry-panel {
      /* position:fixed (top/left set by JS, see positionRestorePanel) so it
         escapes the table wrapper's overflow-x:auto clipping instead of
         getting cut off, which position:absolute doesn't. */
      position: fixed; z-index: 1000;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: .9rem; min-width: 240px;
      box-shadow: 0 8px 24px rgba(0,0,0,.25);
    }
    .expiry-picker-form .chip-group { margin-bottom: .7rem; }
    .expiry-picker-form .gen-custom-input { margin-bottom: .7rem; }
"""

_INVITE_STATUS = {
    "active": ("Active", "#b8bb26"),
    "exhausted": ("Exhausted", "#fe8019"),
    "expired": ("Expired", "#fb4934"),
    "revoked": ("Revoked", "#d3869b"),
}


def _parse_expires_at(expires_at: str | None) -> datetime | None:
    if not expires_at:
        return None
    try:
        return datetime.fromisoformat(expires_at).replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid expires_at format") from exc


def _invite_state(c: InviteCode, now: datetime) -> tuple[str, bool, bool]:
    """Returns (label, is_time_expired, is_use_exhausted).

    The two booleans are independent facts and both can be true at once (a
    code can pass its expires_at *and* hit its use cap). `label` is which of
    the two to show in the single status pill: whichever boundary was
    actually crossed first, using `last_used_at` (set the moment a
    redemption pushes `uses` to `max_uses` — registration already refuses
    once uses >= max_uses, so that's exactly the exhaustion instant) against
    `expires_at`. Falls back to "expired" when a pre-migration exhausted
    code has no `last_used_at` to compare.
    """
    if c.revoked:
        return "revoked", False, False
    is_expired = c.expires_at is not None and c.expires_at <= now
    is_exhausted = c.max_uses is not None and c.uses >= c.max_uses
    if is_expired and is_exhausted:
        if c.last_used_at is not None and c.last_used_at < c.expires_at:
            return "exhausted", is_expired, is_exhausted
        return "expired", is_expired, is_exhausted
    if is_expired:
        return "expired", is_expired, is_exhausted
    if is_exhausted:
        return "exhausted", is_expired, is_exhausted
    return "active", is_expired, is_exhausted


def _render_invites(codes: list[InviteCode], flash: str = "") -> str:
    now = utcnow()
    default_expires = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")
    counts = dict.fromkeys(_INVITE_STATUS, 0)
    rows = ""
    for c in sorted(codes, key=lambda c: c.created_at, reverse=True):
        state, is_expired, is_exhausted = _invite_state(c, now)
        counts[state] += 1
        label, color = _INVITE_STATUS[state]
        # A code can be both time-expired and use-exhausted at once; the
        # "expired"/"exhausted" pill above already picks whichever happened
        # first (for counts/filtering), but show both pills side by side
        # here so the row itself doesn't hide the other true condition.
        if not c.revoked and is_expired and is_exhausted:
            exp_label, exp_color = _INVITE_STATUS["expired"]
            exh_label, exh_color = _INVITE_STATUS["exhausted"]
            status_cell = (
                f'<div class="status-pills">'
                f'<span class="status-pill" style="color:{exp_color};background:{exp_color}22">{exp_label}</span>'
                f'<span class="status-pill" style="color:{exh_color};background:{exh_color}22">{exh_label}</span>'
                f"</div>"
            )
        else:
            status_cell = f'<span class="status-pill" style="color:{color};background:{color}22">{label}</span>'
        code_esc = html.escape(c.code)
        created_by_raw = c.created_by.username if c.created_by else (c.created_by_admin or "")
        created_by = html.escape(created_by_raw) if created_by_raw else "&mdash;"
        expires = _fmt_ts(c.expires_at) if c.expires_at else "&mdash;"
        if c.max_uses is None:
            uses_cell = f'<div class="uses-cell"><span>{c.uses} / &infin;</span></div>'
        else:
            pct = min(100, int(c.uses / c.max_uses * 100))
            uses_cell = (
                f'<div class="uses-cell"><span>{c.uses} / {c.max_uses}</span>'
                f'<div class="uses-track"><div class="uses-fill" style="width:{pct}%;background:{color}"></div></div>'
                f"</div>"
            )
        revoke_btn = ""
        if not c.revoked and not is_expired:
            revoke_btn = (
                f'<form method="post" action="{_P}/invites/{c.id}/revoke"'
                f" onsubmit=\"return confirm('Revoke invite [{code_esc}]?')\""
                f' style="display:contents">'
                f'<button class="btn-sm btn-warn" type="submit">Revoke</button>'
                f"</form>"
            )
        restore_btn = ""
        if state == "revoked":
            restore_btn = (
                f'<form method="post" action="{_P}/invites/{c.id}/restore"'
                f" onsubmit=\"return confirm('Restore invite [{code_esc}]?')\""
                f' style="display:contents">'
                f'<button class="btn-sm btn-good" type="submit">Restore</button>'
                f"</form>"
            )
        reset_uses_btn = ""
        if is_exhausted and not is_expired:
            reset_uses_btn = (
                f'<form method="post" action="{_P}/invites/{c.id}/reset-uses" style="display:contents">'
                f'<button class="btn-sm btn-good" type="submit">Reset uses</button>'
                f"</form>"
            )
        restore_expiry_btn = ""
        if is_expired:
            restore_expiry_btn = f"""
            <details class="restore-expiry">
              <summary class="btn-sm btn-good">Restore</summary>
              <div class="restore-expiry-panel">
                <form method="post" action="{_P}/invites/{c.id}/restore-expiry" class="expiry-picker-form">
                  <div class="chip-group expiry-chip-group" data-for="restore_expires_{c.id}">
                    <button type="button" class="chip active" data-hours="24">24 hours</button>
                    <button type="button" class="chip" data-hours="168">7 days</button>
                    <button type="button" class="chip" data-hours="720">30 days</button>
                    <button type="button" class="chip" data-hours="">Never</button>
                    <button type="button" class="chip" data-custom="1">Custom&hellip;</button>
                  </div>
                  <input class="gen-custom-input" type="datetime-local"
                         id="restore_expires_{c.id}" name="expires_at" value="{default_expires}" hidden>
                  <button class="btn-sm btn-good" type="submit">Confirm</button>
                </form>
              </div>
            </details>"""
        delete_btn = (
            f'<form method="post" action="{_P}/invites/{c.id}/delete"'
            f" onsubmit=\"return confirm('Permanently delete invite [{code_esc}]? This cannot be undone.')\""
            f' style="display:contents">'
            f'<button class="btn-sm btn-purge" type="submit">Delete</button>'
            f"</form>"
        )
        search_raw = f"{c.code} {created_by_raw}".lower()
        search_esc = html.escape(search_raw)
        expires_sort = c.expires_at.isoformat() if c.expires_at else ""
        rows += f"""
        <tr data-status="{state}" data-search="{search_esc}">
          <td class="td-label"><div class="code-cell"><span>{code_esc}</span>
            <button class="btn-copy" type="button" data-code="{code_esc}">Copy</button></div></td>
          <td>{status_cell}</td>
          <td class="td-count" data-sort="{c.uses}">{uses_cell}</td>
          <td class="td-ts" data-sort="{expires_sort}">{expires}</td>
          <td class="td-ts" data-sort="{c.created_at.isoformat()}">{_fmt_ts(c.created_at)}</td>
          <td class="td-email">{created_by}</td>
          <td><div class="td-actions">{revoke_btn}{restore_btn}{reset_uses_btn}{restore_expiry_btn}{delete_btn}</div></td>
        </tr>"""

    empty_row = '<tr><td colspan="7" class="empty">No invite codes yet</td></tr>' if not rows else ""
    stats = "".join(_stat_tile(_INVITE_STATUS[state][0], counts[state], small=True) for state in _INVITE_STATUS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invite Codes &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_SETTINGS_CSS}{_INVITES_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F4E6;</div>
      <div class="brand">
        <span class="brand-name">Invite Codes</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">
    {flash}

    <div class="stats" id="invites-stats">{stats}</div>

    <div class="gen-card">
      <div class="gen-head">
        <div class="gen-icon">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8
                     a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
            <line x1="12" y1="22.08" x2="12" y2="12"/>
          </svg>
        </div>
        <div>
          <div class="gen-title">Generate invite code</div>
          <div class="gen-sub">Create a link that lets someone register while invite-only mode is on.</div>
        </div>
      </div>

      <form method="post" action="{_P}/invites/create" id="invite-form">
        <div class="gen-field">
          <label class="gen-label">Uses</label>
          <div class="chip-group" data-for="max_uses">
            <button type="button" class="chip active" data-value="1">Single use</button>
            <button type="button" class="chip" data-value="5">5 uses</button>
            <button type="button" class="chip" data-value="10">10 uses</button>
            <button type="button" class="chip" data-value="25">25 uses</button>
            <button type="button" class="chip" data-value="">Unlimited</button>
            <button type="button" class="chip" data-custom="1">Custom&hellip;</button>
          </div>
          <input class="gen-custom-input" type="number" id="max_uses" name="max_uses"
                 value="1" min="1" max="10000" hidden>
        </div>

        <div class="gen-field">
          <label class="gen-label">Expires</label>
          <div class="chip-group" data-for="expires_at">
            <button type="button" class="chip active" data-hours="24">24 hours</button>
            <button type="button" class="chip" data-hours="168">7 days</button>
            <button type="button" class="chip" data-hours="720">30 days</button>
            <button type="button" class="chip" data-hours="">Never</button>
            <button type="button" class="chip" data-custom="1">Custom&hellip;</button>
          </div>
          <input class="gen-custom-input" type="datetime-local" id="expires_at" name="expires_at"
                 value="{default_expires}" hidden>
        </div>

        <button class="gen-submit" type="submit">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Generate invite code
        </button>
      </form>
    </div>

    <div class="card">
      <div class="card-header">
        <button class="btn-refresh" id="refresh-btn" type="button" onclick="refreshInvites()" title="Refresh">
          <span class="icon-refresh">&#x21bb;</span>
        </button>
        <h2 class="card-title">All invite codes</h2>
        <span class="pill" id="pill-invites">{len(codes)} total</span>
      </div>
      <div class="invites-toolbar">
        <input class="invites-search" type="text" id="invite-search" placeholder="Search code or admin&hellip;">
        <div class="filter-group" id="invite-status-filter">
          <button type="button" class="chip active" data-status-filter="">All</button>
          <button type="button" class="chip" data-status-filter="active">Active</button>
          <button type="button" class="chip" data-status-filter="exhausted">Exhausted</button>
          <button type="button" class="chip" data-status-filter="expired">Expired</button>
          <button type="button" class="chip" data-status-filter="revoked">Revoked</button>
        </div>
      </div>
      <div style="overflow-x:auto">
      <table id="invites-table">
        <thead>
          <tr>
            <th data-col="0" data-type="text">Code</th>
            <th data-col="1" data-type="text">Status</th>
            <th data-col="2" data-type="num">Uses</th>
            <th data-col="3" data-type="text">Expires</th>
            <th data-col="4" data-type="text">Created</th>
            <th data-col="5" data-type="text">Created by</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="invites-tbody">
          {rows}{empty_row}
        </tbody>
      </table>
      </div>
    </div>

  </div>

  <script>
    // navigator.clipboard needs a secure context (https, or localhost) and in
    // some browsers a user gesture; neither holds for an automatic copy right
    // after page load, so fall back to the execCommand('copy') trick, which
    // works synchronously against a plain textarea instead.
    function copyText(text) {{
      if (navigator.clipboard && window.isSecureContext) {{
        return navigator.clipboard.writeText(text);
      }}
      return new Promise(function (resolve, reject) {{
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var ok = false;
        try {{
          ok = document.execCommand('copy');
        }} catch (e) {{
          ok = false;
        }}
        document.body.removeChild(ta);
        if (ok) resolve(); else reject(new Error('copy failed'));
      }});
    }}

    function bindCopyButtons(root) {{
      root.querySelectorAll('.btn-copy').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          copyText(btn.dataset.code).then(function () {{
            var orig = btn.textContent;
            btn.textContent = 'Copied';
            setTimeout(function () {{ btn.textContent = orig; }}, 1200);
          }}).catch(function () {{}});
        }});
      }});
    }}
    bindCopyButtons(document);

    // auto-copy the code to the clipboard right after it's generated
    var justGenerated = document.querySelector('.just-generated-code');
    if (justGenerated) {{
      copyText(justGenerated.textContent).catch(function () {{}});
    }}

    // auto-hide the "just generated" banner after a few seconds so it
    // doesn't linger once the code has been copied/noted
    var flashEl = document.querySelector('.just-generated');
    if (flashEl) {{
      setTimeout(function () {{
        flashEl.style.opacity = '0';
        setTimeout(function () {{ flashEl.remove(); }}, 400);
      }}, 8000);
    }}

    // Search box + status chips filter the invites table client-side.
    var _invStatusFilter = '';
    function applyInviteFilters() {{
      var q = document.getElementById('invite-search').value.trim().toLowerCase();
      var tbody = document.getElementById('invites-tbody');
      tbody.querySelectorAll('tr[data-status]').forEach(function (row) {{
        var matchesStatus = !_invStatusFilter || row.dataset.status === _invStatusFilter;
        var matchesSearch = !q || row.dataset.search.indexOf(q) !== -1;
        row.style.display = (matchesStatus && matchesSearch) ? '' : 'none';
      }});
    }}
    document.getElementById('invite-search').addEventListener('input', applyInviteFilters);
    document.querySelectorAll('#invite-status-filter .chip').forEach(function (chip) {{
      chip.addEventListener('click', function () {{
        document.querySelectorAll('#invite-status-filter .chip').forEach(function (c) {{
          c.classList.remove('active');
        }});
        chip.classList.add('active');
        _invStatusFilter = chip.dataset.statusFilter;
        applyInviteFilters();
      }});
    }});

    // Sortable columns: click cycles ascending/descending on that column.
    // Date columns carry a data-sort attribute (ISO string) since the
    // displayed "16 Jul 2026 14:41" text doesn't sort chronologically.
    let _invSortCol = null, _invSortAsc = true;
    var _invSortThs = document.querySelectorAll('#invites-table th[data-col]');
    function invSortRows(col, type, asc) {{
      var tbody = document.getElementById('invites-tbody');
      var rows = Array.from(tbody.querySelectorAll('tr[data-status]'));
      rows.sort(function (a, b) {{
        var ca = a.cells[col], cb = b.cells[col];
        var av = ca && ca.dataset.sort !== undefined ? ca.dataset.sort : (ca ? ca.textContent.trim() : '');
        var bv = cb && cb.dataset.sort !== undefined ? cb.dataset.sort : (cb ? cb.textContent.trim() : '');
        var cmp = type === 'num'
          ? (Number(av) || 0) - (Number(bv) || 0)
          : String(av).localeCompare(String(bv), undefined, {{sensitivity: 'base', numeric: true}});
        return asc ? cmp : -cmp;
      }});
      rows.forEach(function (r) {{ tbody.appendChild(r); }});
    }}
    _invSortThs.forEach(function (th) {{
      th.addEventListener('click', function () {{
        var col = Number(th.dataset.col);
        var type = th.dataset.type;
        if (_invSortCol === col) {{ _invSortAsc = !_invSortAsc; }} else {{ _invSortCol = col; _invSortAsc = true; }}
        _invSortThs.forEach(function (h) {{ h.classList.remove('sort-asc', 'sort-desc'); }});
        th.classList.add(_invSortAsc ? 'sort-asc' : 'sort-desc');
        invSortRows(col, type, _invSortAsc);
      }});
    }});

    async function refreshInvites() {{
      const btn = document.getElementById('refresh-btn');
      btn.disabled = true;
      btn.classList.add('loading');
      try {{
        const res = await fetch(window.location.pathname, {{credentials: 'include'}});
        if (!res.ok) throw new Error(res.status);
        const text = await res.text();
        const doc = new DOMParser().parseFromString(text, 'text/html');
        const swap = (id) => {{
          const src = doc.getElementById(id);
          const dst = document.getElementById(id);
          if (src && dst) dst.innerHTML = src.innerHTML;
        }};
        swap('invites-tbody');
        swap('invites-stats');
        swap('pill-invites');
        var tbody = document.getElementById('invites-tbody');
        bindCopyButtons(tbody);
        bindChipGroups(tbody);
        bindExpirySubmitFix(tbody);
        bindRestorePanels(tbody);
        applyInviteFilters();
        if (_invSortCol !== null) {{
          invSortRows(_invSortCol, _invSortThs[_invSortCol].dataset.type, _invSortAsc);
        }}
      }} catch (e) {{
        console.error('Refresh failed:', e);
      }} finally {{
        btn.disabled = false;
        btn.classList.remove('loading');
      }}
    }}

    // Chip groups: clicking a preset sets the paired hidden input's value;
    // "Custom..." instead reveals that input for direct editing. Shared by
    // the create-invite form and every per-row restore-expiry form, and
    // re-bound after refreshInvites() swaps the table body in (new/changed
    // rows bring their own unbound chip groups).
    function bindChipGroups(root) {{
      root.querySelectorAll('.chip-group').forEach(function (group) {{
        if (group.dataset.bound) return;
        group.dataset.bound = '1';
        var input = document.getElementById(group.dataset.for);
        var chips = group.querySelectorAll('.chip');
        chips.forEach(function (chip) {{
          chip.addEventListener('click', function () {{
            chips.forEach(function (c) {{ c.classList.remove('active'); }});
            if (chip.dataset.custom) {{
              chip.classList.add('active');
              input.hidden = false;
              input.value = '';
              input.focus();
              return;
            }}
            input.hidden = true;
            if (input.type === 'datetime-local') {{
              if (chip.dataset.hours) {{
                var d = new Date(Date.now() + Number(chip.dataset.hours) * 3600000);
                d.setSeconds(0, 0);
                input.value = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
              }} else {{
                input.value = '';
              }}
            }} else {{
              input.value = chip.dataset.value;
            }}
            chip.classList.add('active');
          }});
        }});
      }});
    }}
    bindChipGroups(document);

    // datetime-local has no timezone: its value is the user's local wall-clock
    // digits. The chip presets rely on that to *display* correctly, but the
    // server stores expires_at as UTC — convert to a real UTC instant here,
    // right before submit, so "24 hours" actually means 24 hours. Assigning
    // a full ISO string (seconds/ms/"Z") straight back to a datetime-local
    // input is silently rejected by the browser (resets to ""), so switch
    // the input to plain text first. Covers the create-invite form and every
    // per-row restore-expiry form; re-bound after refreshInvites() too.
    function bindExpirySubmitFix(root) {{
      root.querySelectorAll('#invite-form, .expiry-picker-form').forEach(function (form) {{
        if (form.dataset.expiryFixBound) return;
        form.dataset.expiryFixBound = '1';
        form.addEventListener('submit', function () {{
          var input = form.querySelector('input[type="datetime-local"]');
          if (input && input.value) {{
            var iso = new Date(input.value).toISOString();
            input.type = 'text';
            input.value = iso;
          }}
        }});
      }});
    }}
    bindExpirySubmitFix(document);

    // The restore-expiry popover is position:fixed (to escape the table
    // wrapper's overflow-x:auto clipping — see .restore-expiry-panel), so
    // its top/left have to be computed from the <summary> button's actual
    // position on open, clamped to stay inside the viewport. Also closes
    // any other open popover and closes on an outside click.
    function positionRestorePanel(details) {{
      var summary = details.querySelector('summary');
      var panel = details.querySelector('.restore-expiry-panel');
      if (!summary || !panel) return;
      var rect = summary.getBoundingClientRect();
      var panelWidth = panel.offsetWidth || 240;
      var left = Math.min(rect.right - panelWidth, window.innerWidth - panelWidth - 8);
      left = Math.max(8, left);
      var top = Math.min(rect.bottom + 6, window.innerHeight - panel.offsetHeight - 8);
      panel.style.left = left + 'px';
      panel.style.top = top + 'px';
    }}
    function bindRestorePanels(root) {{
      root.querySelectorAll('details.restore-expiry').forEach(function (details) {{
        if (details.dataset.bound) return;
        details.dataset.bound = '1';
        details.addEventListener('toggle', function () {{
          if (details.open) {{
            document.querySelectorAll('details.restore-expiry[open]').forEach(function (other) {{
              if (other !== details) other.open = false;
            }});
            positionRestorePanel(details);
          }}
        }});
      }});
    }}
    bindRestorePanels(document);
    document.addEventListener('click', function (e) {{
      document.querySelectorAll('details.restore-expiry[open]').forEach(function (details) {{
        if (!details.contains(e.target)) details.open = false;
      }});
    }});
  </script>
</body>
</html>"""


@router.get("/invites", response_class=HTMLResponse, include_in_schema=False)
def list_invites(
    generated: str | None = Query(default=None),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    codes = db.query(InviteCode).options(joinedload(InviteCode.created_by)).all()
    flash = ""
    if generated:
        code_esc = html.escape(generated)
        flash = (
            '<div class="just-generated">'
            '<span class="just-generated-label">&#x2713; Generated</span>'
            f'<span class="just-generated-code">{code_esc}</span>'
            f'<button class="btn-copy" type="button" data-code="{code_esc}">Copy</button>'
            "</div>"
        )
    return _render_invites(codes, flash=flash)


@router.post("/invites/create", include_in_schema=False)
def create_invite(
    # FastAPI coerces an empty submitted value to this default only when the
    # field type is Optional — a plain `str` default is NOT applied for an
    # empty string, it only fills a truly missing field. That's exactly the
    # behavior "" (unlimited) vs "5" needs here.
    max_uses: str | None = Form(default=None),  # empty/missing = unlimited uses
    expires_at: str | None = Form(default=None),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    parsed_max_uses: int | None = None
    if max_uses:
        try:
            parsed_max_uses = int(max_uses)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="max_uses must be a whole number") from exc
        if parsed_max_uses < 1:
            raise HTTPException(status_code=422, detail="max_uses must be at least 1")
    parsed_expires = _parse_expires_at(expires_at)
    code = InviteCode(
        code=secrets.token_urlsafe(10),
        created_by_user_id=None,
        created_by_admin=admin_user,
        max_uses=parsed_max_uses,
        uses=0,
        expires_at=parsed_expires,
        revoked=False,
    )
    db.add(code)
    db.commit()
    _log.info(
        "admin=%s generated invite code=%s max_uses=%s expires=%s",
        admin_user,
        code.code,
        parsed_max_uses,
        parsed_expires,
    )
    return RedirectResponse(f"{_P}/invites?generated={quote(code.code)}", status_code=303)


@router.post("/invites/{code_id}/revoke", include_in_schema=False)
def revoke_invite(
    code_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    code = db.get(InviteCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Invite code not found")
    code.revoked = True
    db.commit()
    _log.info("admin=%s revoked invite code id=%s code=%s", admin_user, code_id, code.code)
    return RedirectResponse(f"{_P}/invites", status_code=303)


@router.post("/invites/{code_id}/restore", include_in_schema=False)
def restore_invite(
    code_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Clear the revoked flag; the code's actual state still depends on
    expiry/uses, same as any other code — this just undoes the revoke."""
    code = db.get(InviteCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Invite code not found")
    code.revoked = False
    db.commit()
    _log.info("admin=%s restored invite code id=%s code=%s", admin_user, code_id, code.code)
    return RedirectResponse(f"{_P}/invites", status_code=303)


@router.post("/invites/{code_id}/restore-expiry", include_in_schema=False)
def restore_invite_expiry(
    code_id: int,
    expires_at: str | None = Form(default=None),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Give a time-expired code a new expires_at (or None = never) and reset
    its use count to 0 — a code that expired by time may also have been at
    or near its use cap, so restoring it makes it fully usable again rather
    than immediately falling straight into "exhausted"."""
    code = db.get(InviteCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Invite code not found")
    parsed_expires = _parse_expires_at(expires_at)
    code.expires_at = parsed_expires
    code.uses = 0
    db.commit()
    _log.info(
        "admin=%s restored expired invite id=%s code=%s new_expires=%s",
        admin_user,
        code_id,
        code.code,
        parsed_expires,
    )
    return RedirectResponse(f"{_P}/invites", status_code=303)


@router.post("/invites/{code_id}/reset-uses", include_in_schema=False)
def reset_invite_uses(
    code_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Reset a usage-exhausted code's use counter to 0; max_uses is left
    untouched and the prior use count isn't preserved anywhere."""
    code = db.get(InviteCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Invite code not found")
    code.uses = 0
    db.commit()
    _log.info("admin=%s reset uses on invite id=%s code=%s", admin_user, code_id, code.code)
    return RedirectResponse(f"{_P}/invites", status_code=303)


@router.post("/invites/{code_id}/delete", include_in_schema=False)
def delete_invite(
    code_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Permanently remove the row — unlike revoke, this cannot be undone."""
    code = db.get(InviteCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Invite code not found")
    code_str = code.code
    db.delete(code)
    db.commit()
    _log.info("admin=%s deleted invite code id=%s code=%s", admin_user, code_id, code_str)
    return RedirectResponse(f"{_P}/invites", status_code=303)
