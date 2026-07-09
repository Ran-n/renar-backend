#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.560889
Revised: 2026/07/09 13:01:55.019131
"""

import base64
import io

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from PIL import Image as PILImage
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..config import settings
from ..database import get_db
from ..models import (
    Comment,
    CommentLike,
    EndpointStat,
    Follow,
    Image,
    LoginEvent,
    Notification,
    RequestDay,
    User,
    utcnow,
)
from ..schemas import PasswordChange, ProfileUpdate, Token, UserCreate, UserOut
from ..security import check_login_allowed, client_ip, note_login_failure, note_login_success
from ..storage import delete_image, hash_bytes, store_image

AVATAR_SIZE = 256


def _process_avatar(avatar_b64: str) -> bytes:
    """Decode, downscale to 256px, return normalized JPEG bytes."""
    try:
        img = PILImage.open(io.BytesIO(base64.b64decode(avatar_b64)))
        img = img.convert("RGB")
        img.thumbnail((AVATAR_SIZE, AVATAR_SIZE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not read that image file",
        ) from exc


def _attach_avatar(user: User, raw: bytes, db: Session) -> None:
    """Point the user at the (deduplicated) image row for these bytes."""
    hash_ = hash_bytes(raw)
    image = db.query(Image).filter(Image.hash == hash_).first()
    if image is None:
        store_image(raw)
        image = Image(hash=hash_, size_bytes=len(raw))
        db.add(image)
        db.flush()
    user.avatar_id = image.id


def _gc_image(image_id: int | None, db: Session) -> None:
    """Delete an image row + file once nothing references it anymore."""
    if image_id is None:
        return
    still_used = db.query(User).filter(User.avatar_id == image_id).count()
    if still_used:
        return
    image = db.get(Image, image_id)
    if image:
        delete_image(image.hash)
        db.delete(image)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if not settings.registration_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently closed",
        )
    existing = db.query(User).filter(or_(User.username == data.username, User.email == data.email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_login_allowed(form.username, ip)  # 429 while the account is under backoff
    # form.username accepts either username or email
    user = db.query(User).filter(or_(User.username == form.username, User.email == form.username)).first()
    if user is None or not verify_password(form.password, user.password_hash):
        note_login_failure(form.username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    note_login_success(form.username, ip)  # a correct password shouldn't count as a failed attempt
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been banned")
    now = utcnow()
    user.last_login_at = now
    user.last_active_at = now
    user.login_count = (user.login_count or 0) + 1
    db.add(LoginEvent(user_id=user.id, created_at=now))  # time-series source for the admin panel
    db.commit()
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/profile", response_model=UserOut)
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.username and data.username != user.username:
        if db.query(User).filter(User.username == data.username).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
        user.username = data.username
    if data.email and data.email != user.email:
        if db.query(User).filter(User.email == data.email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already taken")
        user.email = data.email
    if data.language is not None:
        user.language = data.language
    if data.avatar_b64 is not None:
        old_avatar_id = user.avatar_id
        if data.avatar_b64:
            _attach_avatar(user, _process_avatar(data.avatar_b64), db)
        else:
            user.avatar_id = None
        if old_avatar_id != user.avatar_id:
            db.flush()  # session has autoflush off; GC must see the new reference
            _gc_image(old_avatar_id, db)
    db.commit()
    db.refresh(user)
    return user


@router.post("/change_password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(data.new_password)
    db.commit()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # social artifacts don't cascade from User — clean them up explicitly
    my_comment_ids = [c.id for c in db.query(Comment.id).filter(Comment.user_id == user.id)]
    likes = db.query(CommentLike).filter(CommentLike.user_id == user.id)
    if my_comment_ids:
        likes = db.query(CommentLike).filter(
            or_(CommentLike.user_id == user.id, CommentLike.comment_id.in_(my_comment_ids))
        )
    likes.delete(synchronize_session=False)
    db.query(Comment).filter(Comment.user_id == user.id).delete(synchronize_session=False)
    db.query(Follow).filter(or_(Follow.follower_id == user.id, Follow.followed_id == user.id)).delete(
        synchronize_session=False
    )
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(LoginEvent).filter(LoginEvent.user_id == user.id).delete(synchronize_session=False)
    db.query(EndpointStat).filter(EndpointStat.user_id == user.id).delete(synchronize_session=False)
    db.query(RequestDay).filter(RequestDay.user_id == user.id).delete(synchronize_session=False)
    old_avatar_id = user.avatar_id
    db.delete(user)  # media items + episode watches + watch events cascade via ORM
    db.flush()
    _gc_image(old_avatar_id, db)
    db.commit()
