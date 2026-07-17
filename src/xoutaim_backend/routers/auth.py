#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.560889
Revised: 2026/07/16 17:15:51.973438
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import accounts
from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..database import get_db
from ..image_service import gc_image, image_row_for
from ..image_utils import decode_b64_image, normalize_jpeg
from ..models import InviteCode, LoginEvent, User, utcnow
from ..premium import FREE_PROGRESS_STYLES, FREE_THEMES
from ..schemas import PasswordChange, ProfileUpdate, RegistrationStatus, Token, UserCreate, UserOut
from ..security import check_login_allowed, client_ip, note_login_failure, note_login_success
from ..site_settings import get_site_settings

_log = logging.getLogger(__name__)

AVATAR_SIZE = 256
BACKGROUND_MAX = (1280, 480)  # landscape banner: 8:3 aspect


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/registration-status", response_model=RegistrationStatus)
def registration_status(db: Session = Depends(get_db)):
    """Unauthenticated: lets the signup screen decide whether to render an
    invite-code field before the user ever submits the form."""
    ss = get_site_settings(db)
    return RegistrationStatus(registration_open=ss.registration_open, invite_only=ss.invite_only)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    ss = get_site_settings(db)
    if not ss.registration_open:
        _log.info("registration rejected: registration is closed (username=%r)", data.username)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently closed",
        )

    invite: InviteCode | None = None
    if ss.invite_only:
        if not data.invite_code:
            _log.info("registration rejected: no invite code given (username=%r)", data.username)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An invite code is required to register",
            )
        # FOR UPDATE: a single-use code hit by two concurrent registrations
        # must not both pass the uses < max_uses check below — the lock
        # serializes them so the second one sees the first's increment.
        invite = db.query(InviteCode).filter(InviteCode.code == data.invite_code).with_for_update().first()
        if invite is None or invite.revoked:
            _log.info(
                "registration rejected: invalid/revoked invite code=%r (username=%r)",
                data.invite_code,
                data.username,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invite code",
            )
        if invite.expires_at is not None and invite.expires_at <= utcnow():
            _log.info(
                "registration rejected: invite code=%r expired at %s (username=%r)",
                invite.code,
                invite.expires_at,
                data.username,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite code has expired",
            )
        if invite.max_uses is not None and invite.uses >= invite.max_uses:
            _log.info(
                "registration rejected: invite code=%r fully used (%s/%s) (username=%r)",
                invite.code,
                invite.uses,
                invite.max_uses,
                data.username,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite code has been fully used",
            )

    existing = db.query(User).filter(or_(User.username == data.username, User.email == data.email)).first()
    if existing:
        clash = "username" if existing.username == data.username else "email"
        _log.info(
            "registration rejected: %s already taken (username=%r email=%r, existing id=%s)",
            clash,
            data.username,
            data.email,
            existing.id,
        )
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
    if invite is not None:
        invite.uses += 1
    db.commit()
    db.refresh(user)
    if invite is not None:
        _log.info(
            "new user registered: id=%s username=%r via invite code=%r (uses=%s/%s)",
            user.id,
            user.username,
            invite.code,
            invite.uses,
            invite.max_uses,
        )
    else:
        _log.info("new user registered: id=%s username=%r", user.id, user.username)
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
    user.last_active_at = now
    # the single record of this login; counts/last-login are derived from it
    db.add(LoginEvent(user_id=user.id, created_at=now))
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
            user.avatar_id = image_row_for(
                normalize_jpeg(decode_b64_image(data.avatar_b64), (AVATAR_SIZE, AVATAR_SIZE), data.avatar_crop), db
            ).id
        else:
            user.avatar_id = None
        if old_avatar_id != user.avatar_id:
            db.flush()  # session has autoflush off; GC must see the new reference
            gc_image(old_avatar_id, db)
    if data.background_b64 is not None:
        if data.background_b64 and not user.is_premium:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Premium required for background image",
            )
        old_background_id = user.background_id
        if data.background_b64:
            user.background_id = image_row_for(
                normalize_jpeg(decode_b64_image(data.background_b64), BACKGROUND_MAX, data.background_crop), db
            ).id
        else:
            user.background_id = None
        if old_background_id != user.background_id:
            db.flush()  # session has autoflush off; GC must see the new reference
            gc_image(old_background_id, db)
    if data.theme is not None:
        if data.theme not in FREE_THEMES and not user.is_premium:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Premium required for this theme",
            )
        user.theme = data.theme
    if data.show_original_titles is not None:
        user.show_original_titles = data.show_original_titles
    if data.home_hero_enabled is not None:
        user.home_hero_enabled = data.home_hero_enabled
    if data.home_on_launch is not None:
        user.home_on_launch = data.home_on_launch
    if data.home_progress_style is not None:
        if data.home_progress_style not in FREE_PROGRESS_STYLES and not user.is_premium:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Premium required for this progress style",
            )
        user.home_progress_style = data.home_progress_style
    if data.has_seen_welcome is not None:
        user.has_seen_welcome = data.has_seen_welcome
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
    accounts.delete_account(user, db)
