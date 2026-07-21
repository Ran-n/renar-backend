#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 03:02:57.798569
Revised: 2026/07/21 09:51:04.833943

Account deletion: the one purge path, shared by self-service
(DELETE /auth/me) and the admin panel's delete-user action.

Nothing social cascades from User at the DB level, so every dependent row
is cleared explicitly, in FK-safe order. The user's comments are deleted
one by one through the ORM — a bulk DELETE would bypass the relationship
cascades and trip over replies and reports that other users attached to
those comments.
"""

import logging

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
    LoginEvent,
    Notification,
    RequestDay,
    User,
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
    db.delete(user)  # cascades media_items -> episode_watches + watch_events + notifications
    db.flush()
    gc_image(old_avatar_id, db)
    for pid in poster_image_ids | backdrop_image_ids | still_image_ids:
        gc_image(pid, db)
    db.commit()
    _log.info("deleted account id=%s username=%s", user_id, username)
