#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 03:02:57.798569
Revised: 2026/08/24 12:39:04.812933

Account deletion: the one purge path, shared by self-service
(DELETE /auth/me) and the admin panel's delete-user action.

Nothing social cascades from User at the DB level, so every dependent row
is cleared explicitly, in FK-safe order. The user's comments are deleted
one by one through the ORM — a bulk DELETE would bypass the relationship
cascades and trip over replies and reports that other users attached to
those comments.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..media.image_service import gc_image
from ..models import (
    Comment,
    CommentLike,
    CommentReport,
    EmailConfirmationCode,
    EndpointStat,
    EpisodeCustomStill,
    ExportJob,
    Follow,
    ImportJob,
    InviteCode,
    LibraryEntry,
    List,
    ListItem,
    LoginEvent,
    Notification,
    ReleasedUsername,
    RequestDay,
    Review,
    ReviewWhitelist,
    User,
    utcnow,
)
from .export import delete_export

_log = logging.getLogger(__name__)


def delete_account(user: User, db: Session) -> None:
    """Delete a user plus every row that references them, then GC their
    now-unreferenced images. Commits."""
    user_id, username = user.id, user.username
    # Likes and reports the user made on anyone's comments; likes/reports
    # ON the user's own comments fall with the comments below.
    db.query(CommentLike).filter(CommentLike.user_id == user_id).delete(synchronize_session=False)
    db.query(CommentReport).filter(CommentReport.user_id == user_id).delete(synchronize_session=False)
    for comment in db.query(Comment).filter(Comment.user_id == user_id).all():
        db.delete(comment)  # ORM delete cascades the comment's likes, reports and reply subtree
    db.query(Follow).filter((Follow.follower_id == user_id) | (Follow.followed_id == user_id)).delete(
        synchronize_session=False
    )
    db.query(Notification).filter(Notification.user_id == user_id).delete(synchronize_session=False)
    db.query(LoginEvent).filter(LoginEvent.user_id == user_id).delete(synchronize_session=False)
    db.query(EndpointStat).filter(EndpointStat.user_id == user_id).delete(synchronize_session=False)
    db.query(RequestDay).filter(RequestDay.user_id == user_id).delete(synchronize_session=False)
    db.query(EmailConfirmationCode).filter(EmailConfirmationCode.user_id == user_id).delete(synchronize_session=False)
    db.query(ExportJob).filter(ExportJob.user_id == user_id).delete(synchronize_session=False)
    db.query(ImportJob).filter(ImportJob.user_id == user_id).delete(synchronize_session=False)
    # Invite codes this user created: the FK is nullable — NULL it rather than
    # deleting the codes (they may still be valid and in use by others).
    db.query(InviteCode).filter(InviteCode.created_by_user_id == user_id).update(
        {InviteCode.created_by_user_id: None}, synchronize_session=False
    )
    # Bulk deletes (not ORM db.delete(list)) so these are real DELETE
    # statements executed immediately — List has no relationship() back to
    # User, so the unit-of-work flush planner has no dependency information
    # to order an ORM-staged List delete correctly against the User delete
    # below, unlike Comment (which does declare `author: Mapped[User]`).
    own_list_ids = select(List.id).where(List.user_id == user_id)
    db.query(ListItem).filter(ListItem.list_id.in_(own_list_ids)).delete(synchronize_session=False)
    db.query(List).filter(List.user_id == user_id).delete(synchronize_session=False)
    db.query(Review).filter(Review.user_id == user_id).delete(synchronize_session=False)
    db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user_id).delete(synchronize_session=False)
    delete_export(user_id)  # the zip lives on disk, not in a row this delete() touches
    old_avatar_id = user.avatar_id
    # custom poster/backdrop references die with the cascading library entries
    # — collect them first so their files can be GC'd after the delete
    poster_image_ids = {
        pid
        for (pid,) in db.query(LibraryEntry.custom_poster_image_id).filter(
            LibraryEntry.user_id == user_id, LibraryEntry.custom_poster_image_id.isnot(None)
        )
    }
    backdrop_image_ids = {
        bid
        for (bid,) in db.query(LibraryEntry.custom_backdrop_image_id).filter(
            LibraryEntry.user_id == user_id, LibraryEntry.custom_backdrop_image_id.isnot(None)
        )
    }
    # EpisodeCustomStill has no ORM relationship on LibraryEntry (and no DB-level
    # ON DELETE CASCADE), so it must be deleted explicitly before the cascade
    # delete below tries to remove media_items rows. Collect image IDs first.
    item_id_sel = select(LibraryEntry.id).where(LibraryEntry.user_id == user_id)
    still_image_ids = {
        sid
        for (sid,) in db.query(EpisodeCustomStill.still_image_id).filter(
            EpisodeCustomStill.media_item_id.in_(item_id_sel)
        )
    }
    db.query(EpisodeCustomStill).filter(EpisodeCustomStill.media_item_id.in_(item_id_sel)).delete(
        synchronize_session=False
    )
    # Start this username's cooldown before it's gone (see
    # ReleasedUsername's docstring) — checked at registration in
    # routers/auth.py against SiteSettings.username_cooldown_days.
    db.add(ReleasedUsername(username=username, released_at=utcnow()))
    db.delete(user)  # cascades media_items -> episode_watches + watch_events + notifications
    db.flush()
    gc_image(old_avatar_id, db)
    for pid in poster_image_ids | backdrop_image_ids | still_image_ids:
        gc_image(pid, db)
    db.commit()
    _log.info("deleted account id=%s username=%s", user_id, username)


def request_deletion(user: User, db: Session) -> None:
    """Start the grace period (DELETE /auth/me) instead of purging
    immediately — see SiteSettings.deletion_grace_days and the account_purge
    periodic task (task_runs.py / social/notifier.py), which calls
    delete_account above once the window elapses. Logging back in during the
    window cancels it (routers/auth.py's login)."""
    user.deletion_requested_at = utcnow()
    db.commit()
    _log.info("account deletion requested: id=%s username=%s", user.id, user.username)


def cancel_deletion(user: User, db: Session) -> None:
    """Cancel a pending deletion — called both from the explicit
    POST /auth/me/cancel-deletion endpoint and automatically on a successful
    login during the grace period."""
    user.deletion_requested_at = None
    db.commit()
    _log.info("account deletion cancelled: id=%s username=%s", user.id, user.username)


def purge_expired_deletions(db: Session) -> int:
    """Permanently delete every account whose grace period has elapsed — see
    task_runs.py / social/notifier.py's account_purge periodic task. Returns
    the number of accounts purged."""
    from ..site_settings import current as site_settings_current

    cutoff = utcnow() - timedelta(days=site_settings_current().deletion_grace_days)
    stale = db.query(User).filter(User.deletion_requested_at.isnot(None), User.deletion_requested_at < cutoff).all()
    count = len(stale)
    for user in stale:
        delete_account(user, db)
    return count
