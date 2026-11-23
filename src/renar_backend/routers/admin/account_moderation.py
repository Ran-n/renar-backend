#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:03.060053
Revised: 2026/11/22 01:51:03.060053

Admin measures on a whole account: ban and unban, withdraw and restore the
right to post reviews, and delete the account. Each measure records a
moderation decision and e-mails the user the reasons (moderation/
decisions.py); lifting a measure ends its decision, which starts the
decision's 6-month retention.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import ModerationAction, ReviewWhitelist, User, UserReport
from ...moderation.decisions import Measure, end_measure, profile_reporters, record_and_notify
from ...users import accounts
from ...users.auth import require_admin as _require_admin
from ._html import _P
from ._moderation_form import NOT_MODERATION, optional_reason, parse_reason

router = APIRouter()
_log = logging.getLogger(__name__)


def _user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _profile_measure(db: Session, user: User, action: ModerationAction, form: tuple[str, str, str]) -> Measure:
    """A measure on ``user``'s account; anyone who reported the profile is
    told the outcome, and their reports are then cleared by the caller."""
    reason, details, admin_user = form
    return Measure(
        action=action,
        reason=parse_reason(action, reason),
        moderator=admin_user,
        user=user,
        details=details,
        reporters=profile_reporters(db, user.id),
    )


@router.post("/users/{user_id}/ban", include_in_schema=False)
def ban_user(
    user_id: int,
    background_tasks: BackgroundTasks,
    reason: str = Form(default=""),
    details: str = Form(default=""),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    measure = _profile_measure(db, user, ModerationAction.account_suspended, (reason, details, admin_user))
    record_and_notify(db, measure, background_tasks)
    user.banned = True
    user.ban_reason = f"banned by admin={admin_user}"
    db.query(UserReport).filter(UserReport.reported_user_id == user_id).delete(synchronize_session=False)
    db.commit()
    _log.info("admin=%s banned user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users", status_code=303)


@router.post("/users/{user_id}/unban", include_in_schema=False)
def unban_user(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    user.banned = False
    user.ban_reason = None
    end_measure(db, user_id, ModerationAction.account_suspended)
    db.commit()
    _log.info("admin=%s unbanned user id=%s username=%s", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users", status_code=303)


@router.post("/users/{user_id}/whitelist-review", include_in_schema=False)
def whitelist_review(
    user_id: int,
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    end_measure(db, user_id, ModerationAction.review_rights_withdrawn)
    if not db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user_id).first():
        db.add(ReviewWhitelist(user_id=user_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # double-submit race — already whitelisted
    _log.info("admin=%s added user id=%s username=%s to reviewer whitelist", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/unwhitelist-review", include_in_schema=False)
def unwhitelist_review(
    user_id: int,
    background_tasks: BackgroundTasks,
    reason: str = Form(default=NOT_MODERATION),
    details: str = Form(default=""),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Withdraw review rights. With a reason it's a moderation measure and
    the user is told; "Not a moderation measure" records nothing."""
    user = _user_or_404(db, user_id)
    action = ModerationAction.review_rights_withdrawn
    picked = optional_reason(action, reason)
    if picked is not None:
        measure = Measure(action=action, reason=picked, moderator=admin_user, user=user, details=details)
        record_and_notify(db, measure, background_tasks)
    db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user_id).delete(synchronize_session=False)
    db.commit()
    _log.info("admin=%s removed user id=%s username=%s from reviewer whitelist", admin_user, user_id, user.username)
    return RedirectResponse(f"{_P}/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/delete", include_in_schema=False)
def delete_user(
    user_id: int,
    background_tasks: BackgroundTasks,
    reason: str = Form(default=NOT_MODERATION),
    details: str = Form(default=""),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Delete the account. With a reason it's a moderation measure (the
    account is closed for a breach) and the user and the profile's
    reporters are told; "Not a moderation measure" (deleted on request)
    records nothing."""
    user = _user_or_404(db, user_id)
    action = ModerationAction.account_closed
    if optional_reason(action, reason) is not None:
        measure = _profile_measure(db, user, action, (reason, details, admin_user))
        record_and_notify(db, measure, background_tasks)
    username = user.username
    accounts.delete_account(user, db)
    _log.info("admin=%s deleted user id=%s username=%s", admin_user, user_id, username)
    return RedirectResponse(f"{_P}/users", status_code=303)
