#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Admin usage & analytics: site-wide API usage overview and per-endpoint
caller breakdown.
"""

import html
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import EndpointStat, LoginEvent, User, utcnow
from ...users.auth import require_admin as _require_admin
from ._html import (
    _CHART_DAYS,
    _P,
    _daily_counts,
    _endpoint_item,
    _render_daily_chart,
    _render_endpoint_bars,
    _render_hbars,
    _stat_tile,
    _usage_page,
)

router = APIRouter()
_log = logging.getLogger(__name__)


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
