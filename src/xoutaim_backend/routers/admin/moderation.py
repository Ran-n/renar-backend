#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Admin moderation: comment review/deletion and banned-IP management.
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ...database import get_db
from ...models import BannedIP, Comment, CommentLike, CommentReport, Title, User
from ...social.comment_threads import resolve_root_scope
from ...users import security as _security
from ...users.auth import require_admin as _require_admin
from ._html import (
    _BASE_CSS,
    _FAVICON,
    _P,
    _PAGE_CSS,
    _RESPONSIVE_CSS,
    _fmt_ts,
)

router = APIRouter()
_log = logging.getLogger(__name__)


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
        <span class="pill">{len(bans)} entries</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead>
          <tr><th>IP</th><th>Reason</th><th>Banned</th><th></th></tr>
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
    _security.lift_permaban(ban.ip)
    db.delete(ban)
    db.commit()
    _log.info("admin=%s unbanned ip=%s (was: %s)", admin_user, ban.ip, ban.reason)
    return RedirectResponse(f"{_P}/bans", status_code=303)
