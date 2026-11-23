#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.866780
Revised: 2026/11/22 03:03:52.376147

Records moderation decisions and sends their e-mails.

Every moderation action in the admin panel calls ``record_and_notify``: it
writes one ModerationDecision row, then (as a background task, so a slow
mail server never blocks the admin page) e-mails the statement of reasons
to the affected user and the outcome to everyone who reported the content.
The send result is stored on the row and shown on the admin Decisions page;
a failure is logged by users/mailer.py, never dropped.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    CommentReport,
    MailStatus,
    ModerationAction,
    ModerationDecision,
    ModerationReason,
    ReviewReport,
    User,
    UserReport,
    utcnow,
)
from ..users import mailer
from .mail import has_reporter_statement, reporter_statement, user_statement
from .reasons import DISMISSAL_ACTIONS

_log = logging.getLogger(__name__)

# The removed text kept on the decision and quoted in the statement.
EXCERPT_CHARS = 300
# How long a decision is kept after its measure ends (privacy policy,
# Retention: "up to 6 months after", the window to contest it).
RETENTION_DAYS = 183

# Measures that last until lifted; every other action ends when it's taken.
LASTING_ACTIONS = frozenset({ModerationAction.account_suspended, ModerationAction.review_rights_withdrawn})


@dataclass(frozen=True)
class Recipient:
    """Where one e-mail goes, read before the account can disappear."""

    address: str
    language: str
    username: str

    @classmethod
    def of(cls, user: User) -> Recipient:
        return cls(address=user.email, language=user.language, username=user.username)


@dataclass(frozen=True)
class Measure:
    """One moderation action, as the admin endpoint saw it."""

    action: ModerationAction
    reason: ModerationReason
    moderator: str
    user: User
    details: str | None = None
    target_id: int | None = None
    content: str | None = None
    reporters: tuple[Recipient, ...] = field(default_factory=tuple)
    new_username: str = ""


def _excerpt(content: str | None) -> str | None:
    if not content:
        return None
    return content if len(content) <= EXCERPT_CHARS else content[: EXCERPT_CHARS - 1] + "…"


def record_and_notify(db: Session, measure: Measure, background_tasks) -> ModerationDecision:
    """Write the decision row (committed, so it exists even if the e-mail
    fails) and schedule its e-mails. Call it before deleting the content or
    the account, while the user row still exists."""
    now = utcnow()
    dismissal = measure.action in DISMISSAL_ACTIONS
    decision = ModerationDecision(
        action=measure.action,
        reason=measure.reason,
        note=(measure.details or "").strip() or None,
        moderator=measure.moderator,
        user_id=measure.user.id,
        username=measure.user.username,
        target_id=measure.target_id,
        content_excerpt=_excerpt(measure.content),
        from_report=bool(measure.reporters),
        created_at=now,
        measure_ended_at=None if measure.action in LASTING_ACTIONS else now,
        email_status=MailStatus.not_needed if dismissal else MailStatus.pending,
        reporters_notified=0,
    )
    db.add(decision)
    db.commit()
    _log.info(
        "moderation decision id=%s action=%s reason=%s user_id=%s by admin=%s reporters=%d",
        decision.id,
        decision.action,
        decision.reason,
        decision.user_id,
        measure.moderator,
        len(measure.reporters),
    )
    user = None if dismissal else Recipient.of(measure.user)
    background_tasks.add_task(send_statements, decision.id, user, measure.reporters, measure.new_username)
    return decision


def send_statements(
    decision_id: int, user: Recipient | None, reporters: tuple[Recipient, ...], new_username: str = ""
) -> None:
    """Send the decision's e-mails and store the results on its row."""
    db = SessionLocal()
    try:
        decision = db.get(ModerationDecision, decision_id)
        if user is not None:
            mail = user_statement(decision, user.language, new_username)
            decision.email_status = mailer.deliver(user.address, mail.subject, html=mail.html, text=mail.text)
        if reporters and has_reporter_statement(decision.action):
            decision.reporters_notified = sum(_notify_reporter(decision, r) for r in reporters)
        db.commit()
    finally:
        db.close()


def _notify_reporter(decision: ModerationDecision, reporter: Recipient) -> bool:
    mail = reporter_statement(decision, reporter.language, reporter.username)
    return mailer.deliver(reporter.address, mail.subject, html=mail.html, text=mail.text) is MailStatus.sent


def end_measure(db: Session, user_id: int, action: ModerationAction) -> int:
    """Mark the user's open ``action`` decisions as ended (the suspension or
    the withdrawn review rights were lifted), which starts their 6-month
    retention. Returns how many were ended; the caller commits."""
    return (
        db.query(ModerationDecision)
        .filter(
            ModerationDecision.user_id == user_id,
            ModerationDecision.action == action,
            ModerationDecision.measure_ended_at.is_(None),
        )
        .update({ModerationDecision.measure_ended_at: utcnow()}, synchronize_session=False)
    )


def purge_expired_decisions(db: Session, now: datetime) -> int:
    """Delete decisions whose measure ended more than RETENTION_DAYS ago."""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    count = (
        db.query(ModerationDecision)
        .filter(ModerationDecision.measure_ended_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return count


def _reporters(db: Session, reporter_column, target_column, target_id: int) -> tuple[Recipient, ...]:
    users = db.query(User).filter(User.id.in_(db.query(reporter_column).filter(target_column == target_id))).all()
    return tuple(Recipient.of(u) for u in sorted(users, key=lambda u: u.id))


def comment_reporters(db: Session, comment_id: int) -> tuple[Recipient, ...]:
    return _reporters(db, CommentReport.user_id, CommentReport.comment_id, comment_id)


def review_reporters(db: Session, review_id: int) -> tuple[Recipient, ...]:
    return _reporters(db, ReviewReport.reporter_id, ReviewReport.review_id, review_id)


def profile_reporters(db: Session, user_id: int) -> tuple[Recipient, ...]:
    return _reporters(db, UserReport.reporter_id, UserReport.reported_user_id, user_id)
