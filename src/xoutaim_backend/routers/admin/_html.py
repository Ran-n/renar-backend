#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Shared HTML/CSS primitives for the admin control panel.

All CSS constants, rendering helpers, and chart utilities that are used
by more than one admin submodule live here so the submodules stay focused
on their domain logic.
"""

import html
import re
from datetime import timedelta
from urllib.parse import quote

from ...config import settings
from ...models import utcnow

# Configurable so the panel can hide somewhere unguessable while the
# default /admin becomes a honeypot (see security.py).
_P = settings.admin_path.rstrip("/") or "/admin"

# Minimal but correct email check: local@domain.tld
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
    .btn-warn {
      background: rgba(254,128,25,.1); border: 1px solid rgba(254,128,25,.3); color: #fe8019;
    }
    .btn-warn:hover { background: rgba(254,128,25,.2); border-color: rgba(254,128,25,.5); }
    .btn-good {
      background: rgba(184,187,38,.1); border: 1px solid rgba(184,187,38,.3); color: #b8bb26;
    }
    .btn-good:hover { background: rgba(184,187,38,.2); border-color: rgba(184,187,38,.5); }

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


def _stat_tile(label: str, value, small: bool = False) -> str:
    cls = "stat-value sm" if small else "stat-value"
    return f'<div class="stat"><div class="stat-label">{label}</div><div class="{cls}">{value}</div></div>'


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
