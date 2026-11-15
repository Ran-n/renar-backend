#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:19:55.818208
Revised: 2026/11/15 02:45:11.442573

Admin moderation of user reports: reported reviews (with delete) and
reported users (with a link to the user's admin page, where ban and edit
live). Comment reports are shown on the Comment Manager (moderation.py).
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ...database import get_db
from ...models import Review, ReviewReport, User, UserReport
from ...users.auth import require_admin as _require_admin
from ._html import _P, _fmt_ts, _usage_page

router = APIRouter()
_log = logging.getLogger(__name__)

# How many of a target's latest report reasons a row shows.
_LATEST_REASONS = 3
_PAGE_LIMIT = 500

_FLAG_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>'
    '<line x1="4" y1="22" x2="4" y2="15"/>'
    "</svg>"
)


def _count_cell(count: int) -> str:
    return f'<span style="color:#fb4934;font-weight:600">&#x2691; {count}</span>'


def _reasons_cell(reasons: list[str]) -> str:
    """The latest non-empty reasons, one per line; a dash when nobody gave one."""
    shown = [html.escape(r) for r in reasons if r][:_LATEST_REASONS]
    return "<br>".join(shown) if shown else "&mdash;"


def _latest_reasons(db: Session, model: type, target_column, target_ids: list[int]) -> dict[int, list[str]]:
    """`{target_id: [reason, ...]}` newest first, for the targets on the page
    (one query, not one per row)."""
    reasons: dict[int, list[str]] = {}
    if not target_ids:
        return reasons
    rows = (
        db.query(target_column, model.reason)
        .filter(target_column.in_(target_ids))
        .order_by(model.created_at.desc(), model.id.desc())
        .all()
    )
    for target_id, reason in rows:
        reasons.setdefault(target_id, []).append(reason)
    return reasons


def _table(title: str, total: int, headers: list[str], rows: str, empty: str) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = rows or f'<tr><td colspan="{len(headers)}" class="empty">{empty}</td></tr>'
    return f"""
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">{title}</h2>
        <span class="pill">{total} reported</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
      </div>
    </div>"""


def _render_reported_reviews(reviews: list[tuple[Review, int]], reasons: dict[int, list[str]]) -> str:
    rows = ""
    for review, count in reviews:
        name_esc = html.escape(review.author.username) if review.author else "?"
        title_esc = html.escape(review.title_ref.title) if review.title_ref else "(deleted title)"
        rows += f"""
        <tr>
          <td class="td-label"><a class="td-link" href="{_P}/users/{review.user_id}">{name_esc}</a></td>
          <td class="td-email">{title_esc}</td>
          <td><div class="td-text">{html.escape(review.text)}</div></td>
          <td class="td-count">{_count_cell(count)}</td>
          <td><div class="td-text">{_reasons_cell(reasons.get(review.id, []))}</div></td>
          <td class="td-ts">{_fmt_ts(review.created_at)}</td>
          <td><div class="td-actions">
            <form method="post" action="{_P}/reported-reviews/{review.id}/delete"
                  onsubmit="return confirm('Delete this review by [{name_esc}]?')"
                  style="display:contents">
              <button class="btn-sm btn-purge" type="submit">Delete</button>
            </form>
          </div></td>
        </tr>"""
    headers = ["Author", "Title", "Review", "Reports", "Latest reasons", "Posted", ""]
    inner = _table("Reported reviews", len(reviews), headers, rows, "No reported reviews")
    return _usage_page("Reported Reviews", _FLAG_ICON, _P, "Admin", inner)


def _render_reported_users(users: list[tuple[User, int]], reasons: dict[int, list[str]]) -> str:
    rows = ""
    for user, count in users:
        name_esc = html.escape(user.username)
        rows += f"""
        <tr>
          <td class="td-label"><a class="td-link" href="{_P}/users/{user.id}">{name_esc}</a></td>
          <td class="td-count">{_count_cell(count)}</td>
          <td><div class="td-text">{_reasons_cell(reasons.get(user.id, []))}</div></td>
          <td class="td-ts">{_fmt_ts(user.created_at)}</td>
        </tr>"""
    headers = ["User", "Reports", "Latest reasons", "Joined"]
    inner = _table("Reported users", len(users), headers, rows, "No reported users")
    return _usage_page("Reported Users", _FLAG_ICON, _P, "Admin", inner)


@router.get("/reported-reviews", response_class=HTMLResponse, include_in_schema=False)
def list_reported_reviews(
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Every review with at least one report, most reported first."""
    counts = (
        db.query(ReviewReport.review_id, func.count().label("n"))
        .group_by(ReviewReport.review_id)
        .order_by(func.count().desc(), ReviewReport.review_id.desc())
        .limit(_PAGE_LIMIT)
        .all()
    )
    ids = [review_id for review_id, _n in counts]
    reviews_by_id = {
        r.id: r
        for r in db.query(Review)
        .options(joinedload(Review.author), joinedload(Review.title_ref))
        .filter(Review.id.in_(ids))
        .all()
    }
    reviews = [(reviews_by_id[review_id], n) for review_id, n in counts]
    return _render_reported_reviews(reviews, _latest_reasons(db, ReviewReport, ReviewReport.review_id, ids))


@router.post("/reported-reviews/{review_id}/delete", include_in_schema=False)
def delete_reported_review(
    review_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    author = review.author.username if review.author else "?"
    db.delete(review)  # ORM delete cascades the review's reactions and reports
    db.commit()
    _log.info("admin=%s deleted review id=%s author=%s", admin_user, review_id, author)
    return RedirectResponse(f"{_P}/reported-reviews", status_code=303)


@router.get("/reported-users", response_class=HTMLResponse, include_in_schema=False)
def list_reported_users(
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Every user whose profile has at least one report, most reported first."""
    counts = (
        db.query(UserReport.reported_user_id, func.count().label("n"))
        .group_by(UserReport.reported_user_id)
        .order_by(func.count().desc(), UserReport.reported_user_id.desc())
        .limit(_PAGE_LIMIT)
        .all()
    )
    ids = [user_id for user_id, _n in counts]
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}
    users = [(users_by_id[user_id], n) for user_id, n in counts]
    return _render_reported_users(users, _latest_reasons(db, UserReport, UserReport.reported_user_id, ids))
