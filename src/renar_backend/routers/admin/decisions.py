#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:03.152510
Revised: 2026/11/22 03:03:52.580112

Admin Decisions page: every recorded moderation decision, newest first,
with whether its statement of reasons reached the user. A failed or unsent
statement can be sent again while the account still exists.
"""

import html
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import MailStatus, ModerationDecision, User
from ...moderation.decisions import Recipient, send_statements
from ...moderation.reasons import ACTION_LABELS, REASON_LABELS
from ...users.auth import require_admin as _require_admin
from ._html import _P, _fmt_ts, _usage_page

router = APIRouter()
_log = logging.getLogger(__name__)

_PAGE_LIMIT = 500
_RESENDABLE = frozenset({MailStatus.failed, MailStatus.not_configured})
_MAIL_LABELS = {
    MailStatus.pending: ("Sending", "#fabd2f"),
    MailStatus.sent: ("Sent", "#b8bb26"),
    MailStatus.failed: ("Failed", "#fb4934"),
    MailStatus.not_configured: ("Not sent (no mail key)", "#fb4934"),
    MailStatus.not_needed: ("Not needed", "#a89984"),
}
_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3v18"/><path d="M5 7h14"/><path d="M5 7l-3 7h6z"/><path d="M19 7l-3 7h6z"/>'
    "</svg>"
)


def _user_cell(d: ModerationDecision) -> str:
    name = html.escape(d.username)
    if d.user_id is None:
        return f'{name} <span style="color:#a89984">(deleted)</span>'
    return f'<a class="td-link" href="{_P}/users/{d.user_id}">{name}</a>'


def _mail_cell(d: ModerationDecision) -> str:
    label, color = _MAIL_LABELS[d.email_status]
    cell = f'<span style="color:{color};font-weight:600">{label}</span>'
    if d.email_status in _RESENDABLE and d.user_id is not None:
        cell += (
            f'<form method="post" action="{_P}/decisions/{d.id}/resend" style="display:contents">'
            '<button class="btn-sm" type="submit">Send again</button></form>'
        )
    return cell


def _row(d: ModerationDecision) -> str:
    text = html.escape(d.content_excerpt) if d.content_excerpt else "&mdash;"
    note = html.escape(d.note) if d.note else "&mdash;"
    ended = _fmt_ts(d.measure_ended_at) if d.measure_ended_at else "in force"
    return f"""
        <tr>
          <td class="td-ts">{_fmt_ts(d.created_at)}</td>
          <td class="td-label">{html.escape(ACTION_LABELS[d.action])}</td>
          <td>{_user_cell(d)}</td>
          <td class="td-email">{html.escape(REASON_LABELS[d.reason])}</td>
          <td><div class="td-text">{note}</div></td>
          <td><div class="td-text">{text}</div></td>
          <td class="td-count">{"yes" if d.from_report else "no"}</td>
          <td><div class="td-actions">{_mail_cell(d)}</div></td>
          <td class="td-count">{d.reporters_notified}</td>
          <td class="td-ts">{ended}</td>
          <td class="td-email">{html.escape(d.moderator)}</td>
        </tr>"""


def _render(decisions: list[ModerationDecision], total: int) -> str:
    headers = [
        "When",
        "Decision",
        "User",
        "Reason",
        "Note",
        "Content",
        "Report",
        "E-mail",
        "Reporters told",
        "Ended",
        "By",
    ]
    head = "".join(f"<th>{h}</th>" for h in headers)
    rows = "".join(_row(d) for d in decisions)
    body = rows or f'<tr><td colspan="{len(headers)}" class="empty">No decisions yet</td></tr>'
    inner = f"""
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Moderation decisions</h2>
        <span class="pill">{total} kept</span>
        <span class="pill">deleted 6 months after the measure ends</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
      </div>
    </div>"""
    return _usage_page("Moderation Decisions", _ICON, _P, "Admin", inner)


@router.get("/decisions", response_class=HTMLResponse, include_in_schema=False)
def list_decisions(
    _: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(ModerationDecision)
    total = query.count()
    decisions = query.order_by(ModerationDecision.created_at.desc(), ModerationDecision.id.desc()).limit(_PAGE_LIMIT)
    return _render(decisions.all(), total)


@router.post("/decisions/{decision_id}/resend", include_in_schema=False)
def resend_statement(
    decision_id: int,
    background_tasks: BackgroundTasks,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Send a failed or unsent statement of reasons again, to the user's
    current address. Reporters aren't e-mailed twice."""
    decision = db.get(ModerationDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    user = db.get(User, decision.user_id) if decision.user_id is not None else None
    if user is None or decision.email_status not in _RESENDABLE:
        raise HTTPException(status_code=409, detail="This statement can't be sent again")
    decision.email_status = MailStatus.pending
    db.commit()
    background_tasks.add_task(send_statements, decision.id, Recipient.of(user), (), user.username)
    _log.info("admin=%s resent the statement of decision id=%s", admin_user, decision_id)
    return RedirectResponse(f"{_P}/decisions", status_code=303)
