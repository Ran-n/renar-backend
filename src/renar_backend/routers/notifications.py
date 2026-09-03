#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.426784
Revised: 2026/09/02 16:41:42.296149

Notification center endpoints.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Notification, User
from ..schemas import NotificationOut, UnreadCountOut
from ..users.auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])
_log = logging.getLogger(__name__)


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "media_item_id": n.media_item_id,
        "season": n.season,
        "episode": n.episode,
        "read": n.read,
        "created_at": n.created_at,
    }


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.read.is_(False))
    return [_out(n) for n in query.order_by(Notification.created_at.desc()).limit(50)]


@router.get("/unread_count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).count()
    return {"count": count}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    n.read = True
    db.commit()


@router.post("/read_all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update({"read": True})
    db.commit()


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(n)
    db.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.query(Notification).filter(Notification.user_id == user.id).delete()
    db.commit()
