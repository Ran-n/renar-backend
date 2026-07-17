#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.529990
Revised: 2026/07/17 08:07:31.379501

Admin control panel, protected by HTTP Basic credentials from the .env file.

Same layout as the reska APIs: /admin is a tile dashboard, each tile opens a
server-rendered management page.
"""

import html
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import accounts, security, site_settings
from ..auth import hash_password
from ..auth import require_admin as _require_admin
from ..comment_threads import resolve_root_scope
from ..config import settings
from ..database import get_db
from ..models import (
    BannedIP,
    Comment,
    CommentLike,
    CommentReport,
    EndpointStat,
    EpisodeWatch,
    InviteCode,
    LibraryEntry,
    LoginEvent,
    MediaType,
    RequestDay,
    SiteSettings,
    Title,
    User,
    WatchEvent,
    WatchStatus,
    utcnow,
)
from ..site_settings import get_site_settings

# Configurable so the panel can hide somewhere unguessable while the
# default /admin becomes a honeypot (see security.py).
_P = settings.admin_path.rstrip("/") or "/admin"

router = APIRouter(prefix=_P, tags=["admin"])
_log = logging.getLogger(__name__)

# Minimal but correct email check: local@domain.tld — far stricter than the
# previous `"@" not in email` guard, which accepted "nope" as a valid email.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%9B%A0%3C/text%3E%3C/svg%3E"
)

_BASE_CSS = """
    @keyframes spin { to { transform: rotate(360deg); } }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    /* Gruvbox, same ramp as the app theme (frontend themes.py GRUVBOX):
       bg0..bg3 ladder, fg/fg_dim text, bright yellow/orange accents. */
    :root {
      /* native form chrome (date/time picker popups, number spinners,
         scrollbars) follows the OS dark palette instead of defaulting to
         a jarring white popup against this dark theme */
      color-scheme: dark;
      --bg: #282828;
      --surface: #3c3836;
      --surface-hi: #504945;
      --border: #665c54;
      --border-sub: #504945;
      --text: #ebdbb2;
      --text-2: #a89984;
      --text-3: #928374;
      --accent: #fabd2f;
      --orange: #fe8019;
    }

    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      font-size: 14px;
      line-height: 1.5;
    }

    .topbar {
      background: var(--surface); border-bottom: 1px solid var(--border);
      height: 54px; padding: 0 2rem;
      display: flex; align-items: center; gap: .875rem;
    }
    .logo {
      width: 30px; height: 30px;
      background: linear-gradient(135deg, var(--accent), var(--orange));
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 15px; flex-shrink: 0;
    }
    .logo svg { width: 16px; height: 16px; stroke: var(--bg); }
    .brand { display: flex; flex-direction: column; gap: 1px; }
    .brand-name {
      font-size: .85rem; font-weight: 600; color: var(--text);
      letter-spacing: -.01em; line-height: 1;
    }
    .brand-sub { font-size: .68rem; color: var(--text-2); line-height: 1; }
    .topbar-fill { flex: 1; }
    .admin-pill {
      font-size: .68rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
      color: var(--text-3); background: var(--border-sub); border: 1px solid var(--border);
      border-radius: 5px; padding: 3px 9px; text-decoration: none;
      transition: color .15s, border-color .15s;
    }
    .admin-pill:hover { color: var(--text-2); border-color: var(--text-3); }
    .topbar-brand-link {
      display: flex; align-items: center; gap: .875rem;
      text-decoration: none; color: inherit;
      align-self: stretch; padding: 0 .5rem 0 0;
      transition: opacity .15s;
    }
    .topbar-brand-link:hover { opacity: .75; }
"""

# Appended last in every page's <style> tag so these overrides win the
# cascade at matching widths regardless of how the page-specific CSS above
# orders its own `.page`/grid rules.
_RESPONSIVE_CSS = """
    @media (max-width: 640px) {
      .topbar { padding: 0 1rem; gap: .6rem; }
      .brand-sub { display: none; }
      .page { padding: 1.1rem .85rem; }

      .stats { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: .6rem; }
      .stat { padding: .7rem .9rem; }
      .stat-value { font-size: 1.3rem; }

      .card-header { flex-wrap: wrap; row-gap: .4rem; }
      th, td { padding: .5rem .6rem; }

      .detail-head { flex-wrap: wrap; }
      .detail-avatar, .detail-avatar-fallback { width: 48px; height: 48px; }
      .detail-name { font-size: 1.1rem; }

      .charts-grid { grid-template-columns: 1fr; }
      .hbar-row { grid-template-columns: 68px 1fr 30px; gap: .4rem; }

      .settings-grid { grid-template-columns: 1fr; }
      .status-row { gap: .5rem; }

      .gen-card { padding: 1.1rem .9rem; }
      .gen-head { flex-wrap: wrap; }

      .grid { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
      .tile { padding: 1.1rem .9rem; }
    }
"""

_PAGE_CSS = """
    .page { max-width: 1400px; margin: 0 auto; padding: 1.75rem 2rem; }

    .stats {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: .875rem; margin-bottom: 1.5rem;
    }
    .stat {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: .875rem 1.25rem;
    }
    .stat-label {
      font-size: .68rem; font-weight: 500; color: var(--text-2);
      text-transform: uppercase; letter-spacing: .06em; margin-bottom: .3rem;
    }
    .stat-value {
      font-size: 1.6rem; font-weight: 700; color: var(--text);
      letter-spacing: -.025em; font-variant-numeric: tabular-nums; line-height: 1;
    }

    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; overflow: hidden; margin-bottom: 1.25rem;
    }
    .card-header {
      padding: .75rem 1.5rem; border-bottom: 1px solid var(--border-sub);
      display: flex; align-items: center; gap: .65rem;
    }
    .card-title { font-size: .82rem; font-weight: 600; color: var(--text); letter-spacing: .01em; }
    .pill {
      font-size: .68rem; font-weight: 600; background: var(--border-sub);
      color: var(--text-2); border-radius: 9999px; padding: 2px 8px;
    }

    table { width: 100%; border-collapse: collapse; }
    th {
      text-align: left; padding: .5rem 1rem;
      font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
      color: var(--text-3); border-bottom: 1px solid var(--border);
      font-weight: 500; white-space: nowrap;
    }
    th[data-col] { cursor: pointer; user-select: none; }
    th[data-col]:hover { color: var(--text-2); }
    th[data-col]::after { content: ' '; }
    th[data-col].sort-asc::after { content: ' \\2191'; color: var(--accent); }
    th[data-col].sort-desc::after { content: ' \\2193'; color: var(--accent); }
    td { padding: .6rem 1rem; border-bottom: 1px solid var(--border-sub); vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tbody tr { transition: background .1s; }
    tbody tr:hover td { background: var(--surface-hi); }

    .td-label { font-weight: 500; color: var(--text); }
    .td-count { color: var(--text-2); font-variant-numeric: tabular-nums; font-size: .88rem; }
    .td-ts { color: var(--text-3); font-size: .78rem; line-height: 1.35; }
    .td-email { color: var(--text-2); font-size: .82rem; }
    .empty { color: var(--text-3); text-align: center; padding: 3rem; font-size: .85rem; }
    .td-actions { display: flex; align-items: center; gap: .35rem; white-space: nowrap; }

    .avatar {
      width: 26px; height: 26px; border-radius: 50%; object-fit: cover;
      border: 1px solid var(--border); vertical-align: middle;
    }
    .avatar-fallback {
      display: inline-flex; align-items: center; justify-content: center;
      width: 26px; height: 26px; border-radius: 50%;
      background: var(--border-sub); border: 1px solid var(--border);
      color: var(--text-2); font-size: .7rem; font-weight: 600;
    }
    .user-cell { display: flex; align-items: center; gap: .6rem; }

    .btn-refresh {
      background: transparent; border: 1px solid var(--border); color: var(--text-3);
      border-radius: 8px; width: 28px; height: 28px;
      display: flex; align-items: center; justify-content: center;
      font-size: 1rem; line-height: 1;
      transition: color .1s, border-color .1s, background .1s, transform .1s; flex-shrink: 0;
    }
    .btn-refresh:hover { color: var(--text-2); border-color: var(--text-3); background: var(--surface-hi); }
    .btn-refresh:active { transform: scale(.88); background: var(--border-sub); }
    .btn-refresh.loading { pointer-events: none; }
    .btn-refresh.loading .icon-refresh { animation: spin .6s linear infinite; display: inline-block; }
    .btn-refresh:disabled { opacity: .45; cursor: default; }

    button { cursor: pointer; font-family: inherit; border: none; transition: opacity .15s, background .15s; }
    .btn-sm { border-radius: 6px; padding: .2rem .7rem; font-size: .75rem; font-weight: 500; }
    .btn-purge {
      background: rgba(251,73,52,.1); border: 1px solid rgba(251,73,52,.28); color: #fb4934;
    }
    .btn-purge:hover { background: rgba(251,73,52,.2); border-color: rgba(251,73,52,.5); }

    .td-link { color: var(--accent); text-decoration: none; }
    .td-link:hover { text-decoration: underline; }
    .td-text {
      color: var(--text); font-size: .85rem; max-width: 480px;
      white-space: pre-wrap; word-break: break-word;
    }
    .type-pill {
      font-size: .65rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
      color: var(--text-2); background: var(--border-sub); border: 1px solid var(--border);
      border-radius: 5px; padding: 1px 6px; white-space: nowrap;
    }
"""

_DETAIL_CSS = """
    .back-link {
      font-size: .75rem; color: var(--text-3); text-decoration: none;
      display: inline-flex; align-items: center; gap: .3rem; margin-bottom: 1rem;
    }
    .back-link:hover { color: var(--text-2); }

    .detail-head { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    .detail-avatar, .detail-avatar-fallback {
      width: 64px; height: 64px; border-radius: 50%; flex-shrink: 0;
    }
    .detail-avatar { object-fit: cover; border: 1px solid var(--border); }
    .detail-avatar-fallback {
      display: flex; align-items: center; justify-content: center;
      background: var(--border-sub); border: 1px solid var(--border);
      color: var(--text-2); font-size: 1.5rem; font-weight: 600;
    }
    .detail-id { display: flex; flex-direction: column; gap: .25rem; }
    .detail-name {
      font-size: 1.3rem; font-weight: 700; letter-spacing: -.02em; color: var(--text);
      display: flex; align-items: center; gap: .5rem;
    }
    .detail-email { font-size: .85rem; color: var(--text-2); }
    .detail-meta { font-size: .74rem; color: var(--text-3); }

    .stat-value.sm { font-size: 1rem; font-weight: 600; line-height: 1.3; }

    .charts-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1rem; margin-bottom: 1.25rem;
    }
    .chart-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1rem 1.25rem 1.1rem;
    }
    .chart-title { font-size: .82rem; font-weight: 600; color: var(--text); }
    .chart-sub { font-size: .72rem; color: var(--text-2); margin-bottom: .75rem; min-height: 1rem; }
    .chart svg { width: 100%; height: auto; display: block; }
    .chart .baseline { stroke: var(--border); stroke-width: 1; }
    .chart .bar { transition: filter .1s; }
    .chart .bar:hover { filter: brightness(1.25); }
    .chart-x {
      display: flex; justify-content: space-between;
      font-size: .68rem; color: var(--text-3); margin-top: .4rem;
    }
    .chart-empty { color: var(--text-3); font-size: .8rem; padding: 1.75rem 0; text-align: center; }

    .hbars { display: flex; flex-direction: column; gap: .5rem; }
    .hbar-row { display: grid; grid-template-columns: 96px 1fr 34px; align-items: center; gap: .6rem; }
    .hbar-label { font-size: .78rem; color: var(--text-2); }
    .hbar-label.cap { text-transform: capitalize; }
    .hbar-track { background: var(--border-sub); border-radius: 5px; height: 16px; overflow: hidden; }
    .hbar-fill { height: 100%; border-radius: 5px; min-width: 2px; }
    .hbar-count {
      font-size: .78rem; color: var(--text-2);
      font-variant-numeric: tabular-nums; text-align: right;
    }

    /* Requests-by-endpoint list: labels are long, case-sensitive URL paths, so
       each gets its own full-width row (method tag + monospace path) above its bar. */
    .ep-list { display: flex; flex-direction: column; gap: .8rem; }
    .ep-row { display: flex; flex-direction: column; gap: .35rem; }
    .ep-head { display: flex; align-items: baseline; gap: .5rem; }
    .ep-method {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .62rem; font-weight: 700; letter-spacing: .03em;
      padding: 1px 5px; border-radius: 4px; flex-shrink: 0;
      background: var(--border-sub); border: 1px solid var(--border); color: var(--text-2);
    }
    .ep-get { color: #83a598; }
    .ep-post { color: #b8bb26; }
    .ep-put, .ep-patch { color: #fabd2f; }
    .ep-delete { color: #fb4934; }
    .ep-path {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .78rem; color: var(--text); flex: 1; min-width: 0; word-break: break-all;
    }
    .ep-path a { color: inherit; text-decoration: none; }
    .ep-path a:hover { color: var(--accent); text-decoration: underline; }
    .ep-count {
      font-size: .78rem; color: var(--text-2); font-variant-numeric: tabular-nums;
      flex-shrink: 0; margin-left: .5rem;
    }
    .ep-track { background: var(--border-sub); border-radius: 5px; height: 8px; overflow: hidden; }
    .ep-fill { height: 100%; border-radius: 5px; min-width: 2px; background: var(--accent); transition: filter .1s; }
    .ep-row:hover .ep-fill { filter: brightness(1.2); }
    .ep-more {
      display: inline-block; margin-top: .9rem; font-size: .76rem; font-weight: 500;
      color: var(--accent); text-decoration: none;
    }
    .ep-more:hover { text-decoration: underline; }

    /* Instant hover tooltip for chart marks (the native SVG tooltip is too slow) */
    .chart-tip {
      position: fixed; display: none; z-index: 50; pointer-events: none;
      background: var(--surface-hi); border: 1px solid var(--border); color: var(--text);
      font-size: .72rem; padding: 3px 8px; border-radius: 6px; white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0, 0, 0, .45);
    }

    /* Admin account-action forms */
    .actions-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.1rem 1.25rem; margin-bottom: 1.25rem;
    }
    .actions-title { font-size: .82rem; font-weight: 600; color: var(--text); margin-bottom: .9rem; }
    .action-row { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .6rem; }
    .action-row label { font-size: .72rem; color: var(--text-2); width: 92px; flex-shrink: 0; }
    .action-input {
      background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .35rem .6rem; font-size: .82rem; font-family: inherit;
      flex: 1; min-width: 160px;
    }
    .action-input:focus { outline: none; border-color: var(--accent); }
    .btn-save {
      background: var(--border-sub); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .35rem .9rem; font-size: .78rem; font-weight: 500;
    }
    .btn-save:hover { background: var(--border); border-color: var(--text-3); }
    .action-sep { height: 1px; background: var(--border-sub); margin: .9rem 0; }
    .action-danger { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
"""


def _fmt_ts(ts) -> str:
    """Day-month-year, e.g. "16 Jul 2026" — not the ISO year-first order
    str(datetime) gives, which reads ambiguously at a glance."""
    if not ts:
        return "&mdash;"
    date = html.escape(f"{ts.day} {ts:%b %Y}")
    time = html.escape(f"{ts:%H:%M}")
    return f"{date} <span style='opacity:.75'>{time}</span>"


# ---- usage charts (self-contained inline SVG, no chart library) ----

_CHART_DAYS = 30
_CHART_ACCENT = "#fabd2f"  # gruvbox bright yellow (app accent); single-series so identity is the title, not the hue


def _fmt_day(d) -> str:
    # Portable across platforms (avoids %-d / %#d strftime differences).
    return f"{d:%b} {d.day}"


def _daily_counts(timestamps, days: int = _CHART_DAYS) -> list[tuple]:
    """Bucket datetimes into per-day counts for the last `days` days (oldest first)."""
    end = utcnow().date()
    start = end - timedelta(days=days - 1)
    buckets: dict = {}
    for ts in timestamps:
        if ts is None:
            continue
        d = ts.date()
        if start <= d <= end:
            buckets[d] = buckets.get(d, 0) + 1
    return [(start + timedelta(days=i), buckets.get(start + timedelta(days=i), 0)) for i in range(days)]


def _bar_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """A column rounded at the top only, square at the baseline (per the mark spec)."""
    r = min(r, w / 2, h)
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} "
        f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h:.1f} Z"
    )


def _daily_from_map(counts: dict, days: int = _CHART_DAYS) -> list[tuple]:
    """Fill the last `days` days from a pre-aggregated {date: count} map."""
    end = utcnow().date()
    start = end - timedelta(days=days - 1)
    return [(start + timedelta(days=i), counts.get(start + timedelta(days=i), 0)) for i in range(days)]


def _render_daily_chart(
    title: str, series: list[tuple], unit: str, color: str = _CHART_ACCENT, footer: str = ""
) -> str:
    total = sum(c for _, c in series)
    peak = max((c for _, c in series), default=0)
    if peak == 0:
        return (
            f'<div class="chart-card"><div class="chart-title">{html.escape(title)}</div>'
            f'<div class="chart-sub">0 in the last {len(series)} days</div>'
            f'<div class="chart-empty">No activity yet</div>{footer}</div>'
        )

    slot, bw, ph, top = 11.0, 9.0, 80.0, 12.0
    width = len(series) * slot
    height = ph + top
    bars = ""
    for i, (d, c) in enumerate(series):
        bh = (c / peak) * ph if c else 0.0
        if 0 < bh < 2:
            bh = 2.0  # keep a single event visible
        if bh <= 0:
            continue
        x = i * slot + (slot - bw) / 2
        y = top + ph - bh
        label = html.escape(f"{_fmt_day(d)}: {c} {unit}".strip())
        bars += f'<path class="bar" d="{_bar_path(x, y, bw, bh, 3)}" fill="{color}" data-tip="{label}"></path>'
    baseline = f'<line class="baseline" x1="0" y1="{top + ph:.1f}" x2="{width:.1f}" y2="{top + ph:.1f}"/>'
    return (
        f'<div class="chart-card"><div class="chart-title">{html.escape(title)}</div>'
        f'<div class="chart-sub">{total} total &middot; peak {peak}/day</div>'
        f'<div class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        f'aria-label="{html.escape(title)}">{baseline}{bars}</svg></div>'
        f'<div class="chart-x"><span>{html.escape(_fmt_day(series[0][0]))}</span><span>today</span></div>'
        f"{footer}</div>"
    )


def _render_hbars(
    title: str,
    items: list[tuple],
    unit: str,
    color: str = _CHART_ACCENT,
    empty: str = "No items yet",
    cap: bool = False,
) -> str:
    """Horizontal bar breakdown for short labels (media types, usernames).
    `items` are (label, count, href|None); a row with an href becomes a link.
    `cap` title-cases the labels (right for "tv show", wrong for a username or
    a case-sensitive path — those use their own components)."""
    maxv = max((c for _, c, _ in items), default=0)
    total = sum(c for _, c, _ in items)
    label_cls = "hbar-label cap" if cap else "hbar-label"
    if maxv == 0:
        body = f'<div class="chart-empty">{html.escape(empty)}</div>'
    else:
        body = '<div class="hbars">'
        for label, c, href in items:
            pct = (c / maxv) * 100
            fill = f'<div class="hbar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
            label_esc = html.escape(label)
            label_html = f'<a class="td-link" href="{href}">{label_esc}</a>' if href else label_esc
            body += (
                f'<div class="hbar-row"><span class="{label_cls}">{label_html}</span>'
                f'<div class="hbar-track">{fill}</div>'
                f'<span class="hbar-count">{c}</span></div>'
            )
        body += "</div>"
    return (
        f'<div class="chart-card"><div class="chart-title">{html.escape(title)}</div>'
        f'<div class="chart-sub">{total} {unit}</div>{body}</div>'
    )


_METHOD_CLASS = {"GET": "ep-get", "POST": "ep-post", "PUT": "ep-put", "PATCH": "ep-patch", "DELETE": "ep-delete"}


def _endpoint_item(method: str, path: str, count) -> tuple:
    """(method, path, count, drill-down href) for the endpoint components."""
    href = f"{_P}/usage/endpoint?method={quote(method)}&path={quote(path, safe='')}"
    return (method, path, int(count or 0), href)


def _ep_list_html(items: list[tuple], scale_max: int | None = None) -> str:
    """Inner markup for a requests-by-endpoint list. `items` are
    (method, path, count, href|None). Bars scale to `scale_max` (or the local
    max) so a top-N preview and the full page can share one scale if wanted.

    Preserves the true case of the URL path (paths are case-sensitive) and
    renders it in monospace on its own full-width row, so a long path like
    /tmdb/image/{size}/{filename} stays readable instead of wrapping into a
    cramped fixed-width column.
    """
    maxv = scale_max or max((c for _, _, c, _ in items), default=0)
    if maxv == 0:
        return '<div class="chart-empty">No requests recorded yet</div>'
    body = '<div class="ep-list">'
    for method, path, c, href in items:
        pct = (c / maxv) * 100
        mcls = _METHOD_CLASS.get(method.upper(), "")
        path_esc = html.escape(path)
        path_html = f'<a href="{href}">{path_esc}</a>' if href else path_esc
        body += (
            f'<div class="ep-row"><div class="ep-head">'
            f'<span class="ep-method {mcls}">{html.escape(method)}</span>'
            f'<span class="ep-path">{path_html}</span>'
            f'<span class="ep-count">{c}</span></div>'
            f'<div class="ep-track"><div class="ep-fill" style="width:{pct:.0f}%"></div></div>'
            f"</div>"
        )
    return body + "</div>"


def _render_endpoint_bars(items: list[tuple], title: str = "Requests by endpoint") -> str:
    """Full requests-by-endpoint card (every item given)."""
    total = sum(c for _, _, c, _ in items)
    return (
        f'<div class="chart-card"><div class="chart-title">{html.escape(title)}</div>'
        f'<div class="chart-sub">{total} requests across {len(items)} endpoints</div>'
        f"{_ep_list_html(items)}</div>"
    )


# Floating tooltip so hovering a chart bar shows its value instantly (the native
# SVG <title> tooltip has a ~1s delay). Included on every page that has charts.
_CHART_TIP = """
  <div class="chart-tip" id="chart-tip"></div>
  <script>
    (function () {
      var tip = document.getElementById('chart-tip');
      if (!tip) return;
      document.querySelectorAll('[data-tip]').forEach(function (el) {
        el.addEventListener('mouseenter', function () {
          tip.textContent = el.getAttribute('data-tip');
          tip.style.display = 'block';
        });
        el.addEventListener('mousemove', function (e) {
          tip.style.left = (e.clientX + 12) + 'px';
          tip.style.top = (e.clientY + 12) + 'px';
        });
        el.addEventListener('mouseleave', function () { tip.style.display = 'none'; });
      });
    })();
  </script>"""


def _render_users(
    users: list[User],
    item_counts: dict[int, int],
    comment_counts: dict[int, int],
    login_counts: dict[int, int],
    last_logins: dict[int, datetime],
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
  <title>User Manager &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F465;</div>
      <div class="brand">
        <span class="brand-name">User Manager</span>
        <span class="brand-sub">xoutaim</span>
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


_SERVICES = [
    {
        "name": "User Manager",
        "desc": "Inspect and delete user accounts",
        "href": f"{_P}/users",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
            '<circle cx="9" cy="7" r="4"/>'
            '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
            '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
            "</svg>"
        ),
    },
    {
        "name": "Usage & Analytics",
        "desc": "Requests by endpoint and site-wide activity",
        "href": f"{_P}/usage",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3 3v18h18"/>'
            '<rect x="7" y="12" width="3" height="6"/>'
            '<rect x="12" y="8" width="3" height="10"/>'
            '<rect x="17" y="4" width="3" height="14"/>'
            "</svg>"
        ),
    },
    {
        "name": "Comment Manager",
        "desc": "Read and delete user comments",
        "href": f"{_P}/comments",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
            "</svg>"
        ),
    },
    {
        "name": "Banned IPs",
        "desc": "Review and lift permanent honeypot bans",
        "href": f"{_P}/bans",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
            '<line x1="9" y1="9" x2="15" y2="15"/>'
            '<line x1="15" y1="9" x2="9" y2="15"/>'
            "</svg>"
        ),
    },
    {
        "name": "Site Settings",
        "desc": "Registration mode and anti-abuse tuning",
        "href": f"{_P}/settings",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="3"/>'
            '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
            "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09"
            "A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06"
            "A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09"
            "A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06"
            "A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09"
            "a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06"
            "A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09"
            'a1.65 1.65 0 0 0-1.51 1z"/>'
            "</svg>"
        ),
    },
    {
        "name": "Invite Codes",
        "desc": "Generate and revoke registration invite codes",
        "href": f"{_P}/invites",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8'
            'a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'
            '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>'
            '<line x1="12" y1="22.08" x2="12" y2="12"/>'
            "</svg>"
        ),
    },
]

_DASHBOARD_CSS = """
    .page { max-width: 860px; margin: 0 auto; padding: 2.5rem 2rem; }
    .page-heading {
      font-size: 1.35rem; font-weight: 700; letter-spacing: -.02em;
      color: var(--text); margin-bottom: .35rem;
    }
    .page-sub { font-size: .85rem; color: var(--text-2); margin-bottom: 2rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
    .tile {
      display: flex; flex-direction: column; gap: 1rem;
      background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem 1.25rem; text-decoration: none; color: inherit;
      transition: border-color .15s, background .15s, transform .1s; cursor: pointer;
    }
    .tile:hover { background: var(--surface-hi); border-color: rgba(250,189,47,.4); transform: translateY(-2px); }
    .tile:hover .tile-icon { background: rgba(250,189,47,.18); color: #fbf1c7; }
    .tile-icon {
      width: 52px; height: 52px; background: rgba(250,189,47,.12); border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      color: var(--accent); transition: background .15s, color .15s; flex-shrink: 0;
    }
    .tile-icon svg { width: 26px; height: 26px; }
    .tile-name { font-size: .95rem; font-weight: 600; color: var(--text); letter-spacing: -.01em; }
    .tile-desc { font-size: .78rem; color: var(--text-2); margin-top: .15rem; line-height: 1.4; }
"""


def _render_dashboard() -> str:
    tiles = ""
    for svc in _SERVICES:
        tiles += (
            f'<a class="tile" href="{svc["href"]}">'
            f'<div class="tile-icon">{svc["icon"]}</div>'
            f'<div class="tile-body">'
            f'<div class="tile-name">{svc["name"]}</div>'
            f'<div class="tile-desc">{svc["desc"]}</div>'
            f"</div></a>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_DASHBOARD_CSS}{_RESPONSIVE_CSS}</style>
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
      <span class="brand-sub">xoutaim</span>
    </div>
    <div class="topbar-fill"></div>
    <span class="admin-pill">Admin</span>
  </header>
  <div class="page">
    <h1 class="page-heading">Control Panel</h1>
    <p class="page-sub">Select a service to manage.</p>
    <div class="grid">{tiles}</div>
  </div>
</body>
</html>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def admin_dashboard(_: str = Depends(_require_admin)):
    return _render_dashboard()


_USERS_PAGE_SIZE = 200


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


def _stat_tile(label: str, value, small: bool = False) -> str:
    cls = "stat-value sm" if small else "stat-value"
    return f'<div class="stat"><div class="stat-label">{label}</div><div class="{cls}">{value}</div></div>'


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
    return pills


def _render_premium_actions(user: User) -> str:
    """Grant/revoke premium time and approve/revoke the verified badge."""
    uid = user.id
    name_esc = html.escape(user.username)
    if user.is_premium:
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
            f" onsubmit=\"return confirm('Remove the verified badge from [{name_esc}]?')\">"
            f'<button class="btn-sm" type="submit">Remove verified</button></form>'
        )
    else:
        verify_action = (
            f'<form method="post" action="{_P}/users/{uid}/verify" style="display:contents">'
            f'<button class="btn-sm" type="submit">Mark verified</button></form>'
        )
    requested = ""
    deny_action = ""
    if user.verification_requested:
        requested = '<span class="pill" style="margin-left:.4rem">verification requested</span>'
        deny_action = (
            f'<form method="post" action="{_P}/users/{uid}/verify/deny" style="display:contents"'
            f" onsubmit=\"return confirm('Deny the verification request from [{name_esc}]?')\">"
            f'<button class="btn-sm" type="submit">Deny verification request</button></form>'
        )
    return f"""
    <div class="actions-card">
      <div class="actions-title">Premium &amp; badge</div>
      <form class="action-row" method="post" action="{_P}/users/{uid}/premium">
        <label>{premium_state}</label>
        <input class="action-input" type="number" name="days" value="30" min="1" max="3650" required>
        <button class="btn-save" type="submit">Grant days</button>
      </form>
      <div class="action-danger">
        {revoke}
        {verify_action}
        {deny_action}
        {requested}
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
  <title>{name_esc} &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_DETAIL_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F464;</div>
      <div class="brand">
        <span class="brand-name">User Detail</span>
        <span class="brand-sub">xoutaim</span>
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


def _usage_page(title: str, icon: str, back_href: str, back_label: str, inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_DETAIL_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">{icon}</div>
      <div class="brand">
        <span class="brand-name">{html.escape(title)}</span>
        <span class="brand-sub">xoutaim</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{back_href}">{html.escape(back_label)}</a>
  </header>

  <div class="page">
    <a class="back-link" href="{back_href}">&#8592; {html.escape(back_label)}</a>
    {inner}
  </div>
  {_CHART_TIP}
</body>
</html>"""


def _render_usage(totals: dict, endpoint_items: list[tuple], login_series: list, signup_series: list) -> str:
    tiles = "".join([
        _stat_tile("API requests", totals["requests"]),
        _stat_tile("Logins", totals["logins"]),
        _stat_tile("Users", totals["users"]),
        _stat_tile("Active today", totals["active_today"]),
        _stat_tile("Active (7d)", totals["active_7d"]),
    ])
    endpoint_card = _render_endpoint_bars(endpoint_items)
    charts = _render_daily_chart("Connections per day", login_series, "logins") + _render_daily_chart(
        "New signups per day", signup_series, "signups"
    )
    inner = (
        f'<div class="stats">{tiles}</div>'
        f'<div class="charts-grid">{charts}</div>'
        f'<div style="margin-top:1.25rem">{endpoint_card}</div>'
    )
    return _usage_page("Usage & Analytics", "&#x1F4CA;", _P, "Admin", inner)


@router.get("/usage", response_class=HTMLResponse, include_in_schema=False)
def usage_overview(
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    now = utcnow()
    cutoff = now - timedelta(days=_CHART_DAYS)
    endpoint_rows = (
        db.query(EndpointStat.method, EndpointStat.path, func.sum(EndpointStat.count))
        .group_by(EndpointStat.method, EndpointStat.path)
        .all()
    )
    endpoint_rows = sorted(endpoint_rows, key=lambda r: r[2] or 0, reverse=True)
    endpoint_items = [_endpoint_item(m, p, t) for m, p, t in endpoint_rows[:25]]
    totals = {
        "requests": int(db.query(func.sum(EndpointStat.count)).scalar() or 0),
        "logins": db.query(func.count(LoginEvent.id)).scalar() or 0,
        "users": db.query(func.count(User.id)).scalar() or 0,
        "active_today": db.query(func.count(User.id)).filter(User.last_active_at >= now - timedelta(days=1)).scalar()
        or 0,
        "active_7d": db.query(func.count(User.id)).filter(User.last_active_at >= now - timedelta(days=7)).scalar() or 0,
    }
    login_ts = [r[0] for r in db.query(LoginEvent.created_at).filter(LoginEvent.created_at >= cutoff)]
    signup_ts = [r[0] for r in db.query(User.created_at).filter(User.created_at >= cutoff)]
    return _render_usage(totals, endpoint_items, _daily_counts(login_ts), _daily_counts(signup_ts))


def _render_endpoint_detail(method: str, path: str, user_items: list[tuple], total: int) -> str:
    label = html.escape(f"{method} {path}")
    callers = _render_hbars("Callers", user_items, "requests", empty="No requests recorded")
    inner = (
        f'<div class="detail-head"><div class="detail-id">'
        f'<div class="detail-name">{label}</div>'
        f'<div class="detail-meta">{total} requests &middot; {len(user_items)} distinct callers</div>'
        f"</div></div>{callers}"
    )
    return _usage_page(f"{method} {path}", "&#x1F517;", f"{_P}/usage", "Usage", inner)


@router.get("/usage/endpoint", response_class=HTMLResponse, include_in_schema=False)
def endpoint_detail(
    method: str = Query(..., max_length=10),
    path: str = Query(..., max_length=200),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(EndpointStat.user_id, func.sum(EndpointStat.count))
        .filter(EndpointStat.method == method, EndpointStat.path == path)
        .group_by(EndpointStat.user_id)
        .all()
    )
    total = sum(int(c or 0) for _, c in rows)
    uids = [uid for uid, _ in rows if uid is not None]
    names = dict(db.query(User.id, User.username).filter(User.id.in_(uids)).all()) if uids else {}
    items = []
    for uid, c in rows:
        c = int(c or 0)
        if uid is None:
            items.append(("anonymous", c, None))
        else:
            items.append((names.get(uid, f"user #{uid}"), c, f"{_P}/users/{uid}"))
    items.sort(key=lambda r: r[1], reverse=True)
    return _render_endpoint_detail(method, path, items, total)


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


def _comment_target(db: Session, c: Comment) -> str:
    """Human-readable target cell: media-type pill + title (+ SxEy scope).

    A reply doesn't store title_id/season/episode itself (see Comment's
    docstring) — resolve its thread root to render the same label.
    """
    title_id, season, episode = resolve_root_scope(db, c)
    title = db.get(Title, title_id)
    label = html.escape(title.title) if title else "(deleted title)"
    if season is not None and episode is not None:
        label += f' <span class="td-count">S{season}E{episode}</span>'
    if c.parent_id is not None:
        label += ' <span class="td-count">&#x21B3; reply</span>'
    type_label = html.escape(title.media_type.value.replace("_", " ")) if title else ""
    return f'<span class="type-pill">{type_label}</span> {label}'


def _render_comments(
    db: Session,
    comments: list[Comment],
    like_counts: dict[int, int],
    report_counts: dict[int, int],
    total: int,
    filter_user: User | None,
) -> str:
    q = f"?user_id={filter_user.id}" if filter_user else ""
    rows = ""
    for c in comments:
        author = c.author
        name_esc = html.escape(author.username) if author else "?"
        if author and author.avatar:
            avatar = f'<img class="avatar" src="{html.escape(author.avatar)}" alt="">'
        else:
            avatar = f'<span class="avatar-fallback">{name_esc[:1].upper()}</span>'
        author_cell = f'<a class="td-link" href="{_P}/comments?user_id={c.user_id}">{name_esc}</a>'
        n_reports = report_counts.get(c.id, 0)
        report_cell = f'<span style="color:#fb4934;font-weight:600">&#x2691; {n_reports}</span>' if n_reports else "0"
        rows += f"""
        <tr>
          <td class="td-label"><div class="user-cell">{avatar}<span>{author_cell}</span></div></td>
          <td class="td-email">{_comment_target(db, c)}</td>
          <td><div class="td-text">{html.escape(c.text)}</div></td>
          <td class="td-count">{like_counts.get(c.id, 0)}</td>
          <td class="td-count">{report_cell}</td>
          <td class="td-ts">{_fmt_ts(c.created_at)}</td>
          <td><div class="td-actions">
            <form method="post" action="{_P}/comments/{c.id}/delete{q}"
                  onsubmit="return confirm('Delete this comment by [{name_esc}]?')"
                  style="display:contents">
              <button class="btn-sm btn-purge" type="submit">Delete</button>
            </form>
          </div></td>
        </tr>"""

    empty_row = '<tr><td colspan="7" class="empty">No comments</td></tr>' if not rows else ""
    filter_pill = ""
    if filter_user:
        filter_pill = (
            f'<span class="pill">by {html.escape(filter_user.username)}</span>'
            f'<a class="admin-pill" href="{_P}/comments">Clear filter</a>'
        )
    truncated_pill = f'<span class="pill">showing latest {len(comments)}</span>' if len(comments) < total else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comment Manager &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F4AC;</div>
      <div class="brand">
        <span class="brand-name">Comment Manager</span>
        <span class="brand-sub">xoutaim</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Comments</h2>
        <span class="pill">{total} total</span>
        {truncated_pill}
        {filter_pill}
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Author</th>
            <th>Target</th>
            <th>Comment</th>
            <th>Likes</th>
            <th>Reports</th>
            <th>Posted</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows}{empty_row}
        </tbody>
      </table>
      </div>
    </div>
  </div>

</body>
</html>"""


@router.get("/comments", response_class=HTMLResponse, include_in_schema=False)
def list_comments(
    user_id: int | None = Query(default=None, ge=1),
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Comment).options(joinedload(Comment.author))
    filter_user = None
    if user_id is not None:
        filter_user = db.get(User, user_id)
        if not filter_user:
            raise HTTPException(status_code=404, detail="User not found")
        query = query.filter(Comment.user_id == user_id)
    total = query.count()
    comments = query.order_by(Comment.created_at.desc()).limit(500).all()
    like_counts = dict(db.query(CommentLike.comment_id, func.count()).group_by(CommentLike.comment_id).all())
    report_counts = dict(db.query(CommentReport.comment_id, func.count()).group_by(CommentReport.comment_id).all())
    return _render_comments(db, comments, like_counts, report_counts, total, filter_user)


@router.post("/comments/{comment_id}/delete", include_in_schema=False)
def delete_comment(
    comment_id: int,
    user_id: int | None = Query(default=None, ge=1),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    author = comment.author.username if comment.author else "?"
    db.delete(comment)  # ORM delete cascades the comment's likes, reports and reply subtree
    db.commit()
    _log.info("admin=%s deleted comment id=%s author=%s", admin_user, comment_id, author)
    dest = f"{_P}/comments" + (f"?user_id={user_id}" if user_id else "")
    return RedirectResponse(dest, status_code=303)


def _render_bans(bans: list[BannedIP]) -> str:
    rows = ""
    for b in sorted(bans, key=lambda b: b.created_at or "", reverse=True):
        ip_esc = html.escape(b.ip)
        rows += f"""
        <tr>
          <td class="td-label">{ip_esc}</td>
          <td class="td-email">{html.escape(b.reason)}</td>
          <td class="td-ts">{_fmt_ts(b.created_at)}</td>
          <td><div class="td-actions">
            <form method="post" action="{_P}/bans/{b.id}/delete"
                  onsubmit="return confirm('Lift the permanent ban on [{ip_esc}]?')"
                  style="display:contents">
              <button class="btn-sm btn-purge" type="submit">Unban</button>
            </form>
          </div></td>
        </tr>"""

    empty_row = '<tr><td colspan="4" class="empty">No banned IPs</td></tr>' if not rows else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Banned IPs &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
        </svg>
      </div>
      <div class="brand">
        <span class="brand-name">Banned IPs</span>
        <span class="brand-sub">xoutaim</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Permanently banned IPs</h2>
        <span class="pill">{len(bans)} banned</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>IP</th>
            <th>Reason</th>
            <th>Banned at</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows}{empty_row}
        </tbody>
      </table>
      </div>
    </div>
  </div>

</body>
</html>"""


@router.get("/bans", response_class=HTMLResponse, include_in_schema=False)
def list_bans(
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return _render_bans(db.query(BannedIP).all())


@router.post("/bans/{ban_id}/delete", include_in_schema=False)
def unban_ip(
    ban_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    ban = db.get(BannedIP, ban_id)
    if not ban:
        raise HTTPException(status_code=404, detail="Ban not found")
    security.lift_permaban(ban.ip)
    db.delete(ban)
    db.commit()
    _log.info("admin=%s unbanned ip=%s (was: %s)", admin_user, ban.ip, ban.reason)
    return RedirectResponse(f"{_P}/bans", status_code=303)


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
    days: int = Form(...),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not 1 <= days <= 3650:
        raise HTTPException(status_code=422, detail="days must be between 1 and 3650")
    # extend from whichever is later: an active subscription keeps its
    # remaining time, a lapsed one restarts from now
    base = user.premium_until if user.is_premium else utcnow()
    user.premium_until = base + timedelta(days=days)
    db.commit()
    _log.info(
        "admin=%s granted %s premium days to user id=%s username=%s (until %s)",
        admin_user,
        days,
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
    security.reset_login_backoff(user.username)
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


# ---------------------------------------------------------------------------
# Site Settings page
# ---------------------------------------------------------------------------

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
        <div class="settings-title"><span class="icon">&#x23F1;</span>Periodic background tasks</div>
        {
        toggle(
            "episode_check_enabled",
            "episode_check_enabled",
            ss.episode_check_enabled,
            "Episode check",
            "Poll TMDB for new episodes on tracked shows and sync episode history.",
        )
    }
        {
        toggle(
            "film_check_enabled",
            "film_check_enabled",
            ss.film_check_enabled,
            "Film check",
            "Poll TMDB for upcoming release dates on tracked want-to-watch films.",
        )
    }
        {
        toggle(
            "bans_check_enabled",
            "bans_check_enabled",
            ss.bans_check_enabled,
            "Bans check",
            "Periodically drop strike rows nobody has touched in 30 days.",
        )
    }
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
    episode_check_enabled: str | None = Form(default=None),
    film_check_enabled: str | None = Form(default=None),
    bans_check_enabled: str | None = Form(default=None),
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
    ss.episode_check_enabled = episode_check_enabled == "1"
    ss.film_check_enabled = film_check_enabled == "1"
    ss.bans_check_enabled = bans_check_enabled == "1"
    db.commit()
    site_settings.invalidate()
    _log.info(
        "admin=%s updated site settings (invite_only=%s registration_open=%s)",
        admin_user,
        ss.invite_only,
        ss.registration_open,
    )
    return RedirectResponse(f"{_P}/settings?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Invite Codes page
# ---------------------------------------------------------------------------


_INVITES_CSS = """
    .status-pill {
      display: inline-flex; align-items: center; gap: .3rem;
      font-size: .68rem; font-weight: 600; letter-spacing: .02em;
      border-radius: 9999px; padding: 2px 9px; white-space: nowrap;
    }
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
"""

_INVITE_STATUS = {
    "active": ("Active", "#b8bb26"),
    "exhausted": ("Exhausted", "#fe8019"),
    "expired": ("Expired", "#fb4934"),
    "revoked": ("Revoked", "#928374"),
}


def _invite_state(c: InviteCode, now: datetime) -> str:
    if c.revoked:
        return "revoked"
    if c.expires_at is not None and c.expires_at <= now:
        return "expired"
    if c.max_uses is not None and c.uses >= c.max_uses:
        return "exhausted"
    return "active"


def _render_invites(codes: list[InviteCode], flash: str = "") -> str:
    now = utcnow()
    default_expires = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")
    counts = dict.fromkeys(_INVITE_STATUS, 0)
    rows = ""
    for c in sorted(codes, key=lambda c: c.created_at, reverse=True):
        state = _invite_state(c, now)
        counts[state] += 1
        label, color = _INVITE_STATUS[state]
        code_esc = html.escape(c.code)
        created_by = html.escape(c.created_by.username) if c.created_by else "&mdash;"
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
        if state not in ("revoked", "expired"):
            revoke_btn = (
                f'<form method="post" action="{_P}/invites/{c.id}/revoke"'
                f" onsubmit=\"return confirm('Revoke invite [{code_esc}]?')\""
                f' style="display:contents">'
                f'<button class="btn-sm btn-purge" type="submit">Revoke</button>'
                f"</form>"
            )
        rows += f"""
        <tr>
          <td class="td-label"><div class="code-cell"><span>{code_esc}</span>
            <button class="btn-copy" type="button" data-code="{code_esc}">Copy</button></div></td>
          <td><span class="status-pill" style="color:{color};background:{color}22">{label}</span></td>
          <td class="td-count">{uses_cell}</td>
          <td class="td-ts">{expires}</td>
          <td class="td-ts">{_fmt_ts(c.created_at)}</td>
          <td class="td-email">{created_by}</td>
          <td><div class="td-actions">{revoke_btn}</div></td>
        </tr>"""

    empty_row = '<tr><td colspan="7" class="empty">No invite codes yet</td></tr>' if not rows else ""
    stats = "".join(_stat_tile(_INVITE_STATUS[state][0], counts[state], small=True) for state in _INVITE_STATUS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invite Codes &middot; xoutaim</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_SETTINGS_CSS}{_INVITES_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x1F4E6;</div>
      <div class="brand">
        <span class="brand-name">Invite Codes</span>
        <span class="brand-sub">xoutaim</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
  </header>

  <div class="page">
    {flash}

    <div class="stats">{stats}</div>

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
        <h2 class="card-title">All invite codes</h2>
        <span class="pill">{len(codes)} total</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Status</th>
            <th>Uses</th>
            <th>Expires</th>
            <th>Created</th>
            <th>Created by</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows}{empty_row}
        </tbody>
      </table>
      </div>
    </div>

  </div>

  <script>
    document.querySelectorAll('.btn-copy').forEach(function (btn) {{
      btn.addEventListener('click', function () {{
        navigator.clipboard.writeText(btn.dataset.code).then(function () {{
          var orig = btn.textContent;
          btn.textContent = 'Copied';
          setTimeout(function () {{ btn.textContent = orig; }}, 1200);
        }});
      }});
    }});

    // Chip groups: clicking a preset sets the paired hidden input's value;
    // "Custom..." instead reveals that input for direct editing.
    document.querySelectorAll('.chip-group').forEach(function (group) {{
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
    parsed_expires: datetime | None = None
    if expires_at:
        try:
            parsed_expires = datetime.fromisoformat(expires_at).replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid expires_at format") from exc
    code = InviteCode(
        code=secrets.token_urlsafe(10),
        created_by_user_id=None,
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
