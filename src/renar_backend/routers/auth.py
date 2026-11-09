#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.560889
Revised: 2026/11/09 11:49:59.719632
"""

import html
import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..events import publish as publish_event
from ..media.image_service import gc_image, image_row_for
from ..media.image_utils import decode_b64_image, normalize_jpeg
from ..models import EmailConfirmationCode, InviteCode, LoginEvent, ReleasedUsername, User, utcnow
from ..schemas import (
    ChangeUnconfirmedEmailRequest,
    ChangeUnconfirmedEmailResult,
    ChangeUnconfirmedEmailSessionRequest,
    ConfirmEmailRequest,
    ConfirmEmailResult,
    ConfirmEmailSessionRequest,
    PasswordChange,
    ProfileUpdate,
    RegistrationStatus,
    ResendConfirmationRequest,
    Token,
    TurnstileSession,
    TurnstileTokenStatus,
    UserCreate,
    UserOut,
)
from ..site_settings import get_site_settings
from ..users import accounts
from ..users.auth import create_access_token, get_current_user, hash_password, verify_password
from ..users.email_confirmation import (
    MAX_ATTEMPTS,
    check_resend_allowed,
    create_and_send_code,
    note_resend,
    verify_code,
)
from ..users.premium import FREE_EPISODE_LABEL_STYLES, FREE_PROGRESS_STYLES, FREE_THEMES, premium_active
from ..users.security import check_login_allowed, client_ip, note_login_failure, note_login_success
from ..users.turnstile import (
    clear_widget_session,
    get_widget_token,
    new_widget_session,
    set_widget_token,
    verify_turnstile,
    widget_html,
    widget_session_exists,
)

_log = logging.getLogger(__name__)

AVATAR_SIZE = 256
BACKGROUND_MAX = (1280, 480)  # landscape banner: 8:3 aspect


def _normalize_email(email: str) -> str:
    return email.strip().lower()


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/registration-status", response_model=RegistrationStatus)
def registration_status(request: Request, response: Response, db: Session = Depends(get_db)):
    """Unauthenticated: lets the signup screen decide whether to render an
    invite-code field, and whether/with which site key to render the
    Turnstile widget, before the user ever submits the form.

    no-store: an admin flipping the Turnstile toggle off must reflect on the
    very next app launch, not whenever some carrier/ISP transparent proxy
    along the way decides its unmarked cache entry has expired — this
    response has none of the validators (ETag/Last-Modified) that would
    make a conditional revalidation possible anyway, so a cache can only
    ever serve it stale, never for free."""
    response.headers["Cache-Control"] = "no-store"
    ss = get_site_settings(db)
    site_key = settings.turnstile_site_key_for(request.url.hostname, ss.turnstile_dev_hostnames)
    return RegistrationStatus(
        registration_open=ss.registration_open,
        invite_only=ss.invite_only,
        turnstile_site_key=(site_key or None) if ss.turnstile_enabled else None,
        email_confirmation_enabled=ss.email_confirmation_enabled,
    )


@router.post("/turnstile-session", response_model=TurnstileSession)
def turnstile_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """Unauthenticated: one-time session for the register screen's Turnstile
    widget (see users/turnstile.py's module docstring for why this lives on
    the backend rather than the frontend). 404 if Turnstile isn't currently
    configured/enabled, matching registration_status's own turnstile_site_key
    — a client that saw a null site key there has no reason to call this."""
    response.headers["Cache-Control"] = "no-store"
    ss = get_site_settings(db)
    site_key = settings.turnstile_site_key_for(request.url.hostname, ss.turnstile_dev_hostnames)
    if not ss.turnstile_enabled or not site_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turnstile is not configured")
    return TurnstileSession(session_id=new_widget_session(db), site_key=site_key)


@router.get("/turnstile-widget/{session_id}", response_class=HTMLResponse, include_in_schema=False)
def turnstile_widget(
    request: Request,
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    theme: str = "dark",
    standalone: bool = False,
):
    response.headers["Cache-Control"] = "no-store"
    if not widget_session_exists(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session expired — reload the register page")
    ss = get_site_settings(db)
    site_key = settings.turnstile_site_key_for(request.url.hostname, ss.turnstile_dev_hostnames)
    return widget_html(site_key, session_id, theme, standalone=standalone)


@router.post("/turnstile-callback/{session_id}", response_class=PlainTextResponse, include_in_schema=False)
def turnstile_callback(session_id: str, token: str, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if not set_widget_token(db, session_id, token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session expired")
    return "ok"


@router.get("/turnstile-token/{session_id}", response_model=TurnstileTokenStatus)
def turnstile_token(session_id: str, response: Response, db: Session = Depends(get_db)):
    """Polled by the register screen (see turnstile_field.py's _poll_for_token)
    until the widget's callback reports a resolved token. no-store matters
    even more here than on registration_status: a cache serving a stale
    {"token": null} would make the poll loop wait out its full timeout and
    never see a token that already resolved."""
    response.headers["Cache-Control"] = "no-store"
    token = get_widget_token(db, session_id)
    if token:
        clear_widget_session(db, session_id)
    return TurnstileTokenStatus(token=token)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ss = get_site_settings(db)
    if not ss.registration_open:
        _log.info("registration rejected: registration is closed (username=%r)", data.username)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently closed",
        )

    secret_key = settings.turnstile_secret_key_for(request.url.hostname, ss.turnstile_dev_hostnames)
    if not verify_turnstile(
        data.turnstile_token, client_ip(request), enabled=ss.turnstile_enabled, secret_key=secret_key
    ):
        _log.info("registration rejected: turnstile verification failed (username=%r)", data.username)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human verification failed — please try again",
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

    email = _normalize_email(data.email)
    existing = db.query(User).filter(or_(User.username == data.username, User.email == email)).first()
    if existing:
        clash = "username" if existing.username == data.username else "email"
        _log.info(
            "registration rejected: %s already taken (username=%r email=%r, existing id=%s)",
            clash,
            data.username,
            email,
            existing.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )
    cooldown_cutoff = utcnow() - timedelta(days=ss.username_cooldown_days)
    on_cooldown = (
        db.query(ReleasedUsername)
        .filter(ReleasedUsername.username == data.username, ReleasedUsername.released_at >= cooldown_cutoff)
        .first()
    )
    if on_cooldown is not None:
        _log.info(
            "registration rejected: username=%r released %s, still on %s-day cooldown",
            data.username,
            on_cooldown.released_at,
            ss.username_cooldown_days,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )
    user = User(
        username=data.username,
        email=email,
        password_hash=hash_password(data.password),
        # Feature disabled: skip the confirmation step entirely rather than
        # creating an account that can never be gated on it (see
        # SiteSettings.email_confirmation_enabled's docstring in models.py).
        email_confirmed=not ss.email_confirmation_enabled,
        email_confirmation_bypassed=not ss.email_confirmation_enabled,
    )
    db.add(user)
    if invite is not None:
        invite.uses += 1
        invite.last_used_at = utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Two registrations with the same username/email raced past the SELECT
        # check above — treat identically to the pre-commit duplicate check.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        ) from None
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
    if ss.email_confirmation_enabled:
        create_and_send_code(db, user, "register", user.email, background_tasks)
    return user


@router.post("/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_login_allowed(form.username, ip)  # 429 while the account is under backoff
    if "\x00" in form.username:
        # Postgres text columns reject NUL outright — filtering by it below
        # would otherwise be an unhandled DataError (500), not a normal
        # login rejection. No account with a NUL byte in its username can
        # exist (schemas.py's UserCreate rejects it at registration), so
        # this can never be a real login — treat it exactly like one.
        note_login_failure(form.username, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
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
    if (
        not user.email_confirmed
        and (utcnow() - user.created_at).days >= get_site_settings(db).email_confirmation_grace_days
    ):
        # distinct, machine-checkable detail (not a generic message) so the
        # frontend routes to the confirm-email screen instead of a dead end —
        # see users/email_confirmation.py's module docstring for why this
        # exists (closing the ranking-exploit gap a captcha alone doesn't).
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email_not_confirmed")
    if user.deletion_requested_at is not None:
        # "no obligation" default, same spirit as the email-confirmation
        # bypass: logging back in during the grace period is itself the
        # signal the user wants to keep the account, no separate confirm
        # step required — see accounts.cancel_deletion.
        accounts.cancel_deletion(user, db)
    now = utcnow()
    user.last_active_at = now
    # the single record of this login; counts/last-login are derived from it
    db.add(LoginEvent(user_id=user.id, created_at=now))
    db.commit()
    return Token(access_token=create_access_token(user.id))


def _authenticate_for_confirmation(username: str, password: str, ip: str, db: Session) -> User:
    """Shared credential check for /confirm-email and /resend-confirmation —
    both are deliberately credential-based rather than bearer-token-based
    (see ConfirmEmailRequest's docstring): once the login grace period
    expires, an unconfirmed user has no way to obtain a token at all, so a
    token-gated endpoint would lock them out of ever confirming. Reuses the
    same per-account throttle as /auth/login so this can't be used to
    brute-force passwords either."""
    check_login_allowed(username, ip)
    user = db.query(User).filter(or_(User.username == username, User.email == username)).first()
    if user is None or not verify_password(password, user.password_hash):
        note_login_failure(username, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    note_login_success(username, ip)
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been banned")
    return user


def _confirm_email_code(user: User, code: str, db: Session, background_tasks: BackgroundTasks) -> ConfirmEmailResult:
    code_row = (
        db.query(EmailConfirmationCode)
        .filter(EmailConfirmationCode.user_id == user.id, EmailConfirmationCode.consumed_at.is_(None))
        .order_by(EmailConfirmationCode.created_at.desc())
        .first()
    )
    if code_row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No confirmation is pending")
    if code_row.expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code has expired — request a new one")
    if code_row.attempts >= MAX_ATTEMPTS:
        code_row.consumed_at = utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many attempts — request a new code")
    if not verify_code(code, code_row.code_hash):
        code_row.attempts += 1
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect code")

    code_row.consumed_at = utcnow()
    if code_row.purpose == "register":
        user.email_confirmed = True
        # A bypassed account voluntarily completing the real flow (see
        # _resend_confirmation) graduates to a genuine confirmation —
        # nothing was obligatory here, but once they've done it for real
        # the "never verified" caveat no longer applies.
        user.email_confirmation_bypassed = False
        db.commit()
        return ConfirmEmailResult(status="confirmed")
    elif code_row.purpose == "change_authorize":
        # the OLD address approved the change — not done yet: the NEW
        # (pending) address still has to prove ownership of itself.
        db.commit()
        create_and_send_code(db, user, "change_confirm", user.pending_email, background_tasks)
        return ConfirmEmailResult(status="change_pending_new_email")
    elif code_row.purpose == "change_confirm":
        # the new address just proved ownership — complete the swap
        user.email = user.pending_email
        user.pending_email = None
        user.email_confirmed = True
        db.commit()
        return ConfirmEmailResult(status="confirmed")
    else:
        _log.error(
            "unknown email confirmation purpose %r for user id=%s — refusing to mutate",
            code_row.purpose,
            user.id,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown confirmation purpose")


@router.post("/confirm-email", response_model=ConfirmEmailResult)
def confirm_email(
    data: ConfirmEmailRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    user = _authenticate_for_confirmation(data.username, data.password, client_ip(request), db)
    return _confirm_email_code(user, data.code, db, background_tasks)


@router.post("/confirm-email-session", response_model=ConfirmEmailResult)
def confirm_email_session(
    data: ConfirmEmailSessionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Same as /confirm-email but for a user who's already holding a valid
    token — the still-logged-in-but-unconfirmed case (e.g. a restored
    session), where asking for the password again would be redundant since
    the token already proves identity. Only reachable while the token is
    valid, i.e. inside the grace period; /confirm-email's credential check
    stays the only route once that expires and the token is gone."""
    return _confirm_email_code(user, data.code, db, background_tasks)


def _change_unconfirmed_email(
    user: User, email: str, db: Session, background_tasks: BackgroundTasks
) -> ChangeUnconfirmedEmailResult:
    if user.email_confirmed or user.pending_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already confirmed — use the profile email-change flow instead",
        )

    new_email = _normalize_email(email)
    if new_email != user.email and db.query(User).filter(User.email == new_email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already taken")

    user.email = new_email
    create_and_send_code(db, user, "register", user.email, background_tasks)
    return ChangeUnconfirmedEmailResult(email=user.email)


@router.post("/change-unconfirmed-email", response_model=ChangeUnconfirmedEmailResult)
def change_unconfirmed_email(
    data: ChangeUnconfirmedEmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Fix a typo'd registration email before ever confirming — a direct
    rewrite of `user.email`, not the two-step change_authorize/change_confirm
    dance `update_profile` uses for an already-confirmed account. That's
    deliberate, not a shortcut: the two-step flow exists to stop an attacker
    who's obtained a password from silently redirecting a real account's
    email, by requiring the CURRENT (real, reachable) address to approve the
    change first. Pre-first-confirmation there's no current reachable
    address to protect — the whole point of this endpoint is that the one on
    file might be wrong — so that protection doesn't apply yet.

    Only reachable in that exact window: rejects once the account has ever
    completed a confirmation (`email_confirmed`) or has a change already in
    flight (`pending_email` set) — both cases must go through the two-step
    flow instead."""
    user = _authenticate_for_confirmation(data.username, data.password, client_ip(request), db)
    return _change_unconfirmed_email(user, data.email, db, background_tasks)


@router.post("/change-unconfirmed-email-session", response_model=ChangeUnconfirmedEmailResult)
def change_unconfirmed_email_session(
    data: ChangeUnconfirmedEmailSessionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Same as /change-unconfirmed-email but for a user who's already holding
    a valid token — the still-logged-in-but-unconfirmed case (e.g. a restored
    session), where asking for the password again would be redundant since
    the token already proves identity. Only reachable while the token is
    valid, i.e. inside the grace period; /change-unconfirmed-email's
    credential check stays the only route once that expires and the token is
    gone."""
    return _change_unconfirmed_email(user, data.email, db, background_tasks)


def _resend_confirmation(user: User, db: Session, background_tasks: BackgroundTasks) -> None:
    # A bypassed account (registered while confirmation wasn't required) is
    # already `email_confirmed`, but never proved ownership for real — let it
    # through so the profile's optional "verify your email" action has
    # something to call. Only a genuinely-confirmed account is rejected here.
    if user.email_confirmed and not user.email_confirmation_bypassed and not user.pending_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already confirmed")

    retry_after = check_resend_allowed(user.username)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many resend requests. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )
    note_resend(user.username)

    if user.pending_email:
        latest = (
            db.query(EmailConfirmationCode)
            .filter(EmailConfirmationCode.user_id == user.id, EmailConfirmationCode.consumed_at.is_(None))
            .order_by(EmailConfirmationCode.created_at.desc())
            .first()
        )
        if latest and latest.purpose == "change_confirm":
            create_and_send_code(db, user, "change_confirm", user.pending_email, background_tasks)
        else:
            create_and_send_code(db, user, "change_authorize", user.email, background_tasks)
    else:
        create_and_send_code(db, user, "register", user.email, background_tasks)


@router.post("/resend-confirmation", status_code=status.HTTP_204_NO_CONTENT)
def resend_confirmation(
    data: ResendConfirmationRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    user = _authenticate_for_confirmation(data.username, data.password, client_ip(request), db)
    _resend_confirmation(user, db, background_tasks)


@router.post("/resend-confirmation-session", status_code=status.HTTP_204_NO_CONTENT)
def resend_confirmation_session(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bearer-token variant of /resend-confirmation — see
    confirm_email_session's docstring."""
    _resend_confirmation(user, db, background_tasks)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = UserOut.model_validate(current_user)
    if not current_user.email_confirmed:
        grace_days = get_site_settings(db).email_confirmation_grace_days
        elapsed_days = (utcnow() - current_user.created_at).days
        out.grace_days_remaining = max(0, grace_days - elapsed_days)
    if current_user.deletion_requested_at is not None:
        deletion_grace_days = get_site_settings(db).deletion_grace_days
        elapsed_days = (utcnow() - current_user.deletion_requested_at).days
        out.deletion_grace_days_remaining = max(0, deletion_grace_days - elapsed_days)
    from .reviews import is_whitelisted_reviewer

    out.can_review = is_whitelisted_reviewer(current_user.id, db)
    out.is_reviewer = out.can_review
    return out


@router.patch("/profile", response_model=UserOut)
def update_profile(
    data: ProfileUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.username and data.username != user.username:
        if db.query(User).filter(User.username == data.username).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
        user.username = data.username
    if data.email:
        new_email = _normalize_email(data.email)
        if new_email != user.email:
            if db.query(User).filter(User.email == new_email).first():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already taken")
            # Two-step change (see TODO.md): `email` itself doesn't
            # move yet — the OLD address must first authorize the change,
            # then the NEW address must prove it's actually reachable.
            user.pending_email = new_email
            user.email_confirmed = False
            create_and_send_code(db, user, "change_authorize", user.email, background_tasks)
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
        if data.background_b64 and not premium_active(user, "background"):
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
        if data.theme not in FREE_THEMES and not premium_active(user, "themes"):
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
        if data.home_progress_style not in FREE_PROGRESS_STYLES and not premium_active(user, "progress_style"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Premium required for this progress style",
            )
        user.home_progress_style = data.home_progress_style
    if data.episode_label_style is not None:
        if data.episode_label_style not in FREE_EPISODE_LABEL_STYLES and not premium_active(user, "episode_label"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Premium required for this episode label style",
            )
        user.episode_label_style = data.episode_label_style
    if data.has_seen_welcome is not None:
        user.has_seen_welcome = data.has_seen_welcome
    db.commit()
    db.refresh(user)
    # push to every other open session on this account (see routers/events.py)
    # so a language/theme/etc. change is picked up without waiting on a poll
    if any(
        f is not None
        for f in (
            data.language,
            data.theme,
            data.show_original_titles,
            data.home_hero_enabled,
            data.home_progress_style,
            data.episode_label_style,
            data.avatar_b64,
            data.background_b64,
        )
    ):
        publish_event(user.id, "settings_changed")
    return user


@router.post("/change_password", response_model=Token)
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
    user.password_changed_at = utcnow()
    db.commit()
    # Changing the password invalidates every token issued before this
    # moment (see get_current_user) — including the one this request was
    # authenticated with, so hand back a fresh one for the caller's own session.
    return Token(access_token=create_access_token(user.id))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Starts the deletion grace period (see accounts.request_deletion) —
    does NOT purge immediately. The account, its token, and its data all
    stay fully usable until the account_purge periodic task removes it past
    SiteSettings.deletion_grace_days, or the user cancels (below) or simply
    logs back in (login() auto-cancels)."""
    accounts.request_deletion(user, db)


@router.post("/me/cancel-deletion", response_model=UserOut)
def cancel_account_deletion(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    accounts.cancel_deletion(user, db)
    return UserOut.model_validate(user)


# Google Play policy requires an account-deletion request to be reachable
# *without* installing the app (a plain hosted web page), in addition to the
# in-app DELETE /auth/me above — see TODO.md's "Account-deletion page
# needs a web-reachable path" entry. This reuses the same grace-period
# deletion (accounts.request_deletion) and the same credential-check/
# rate-limit helper /confirm-email already relies on, rather than a second
# deletion path or a second brute-force surface.
_ACCOUNT_DELETION_STYLE = """
  html{height:100%;margin:0;background:#1d2021;color:#ebdbb2;
    font-family:system-ui,-apple-system,Segoe UI,sans-serif;}
  body{margin:0;min-height:100%;display:flex;align-items:center;justify-content:center;padding:2rem 1rem;}
  .card{max-width:26rem;width:100%;background:#282828;border-radius:12px;padding:1.75rem;}
  h1{font-size:1.25rem;margin:0 0 .75rem;}
  p{font-size:.9rem;line-height:1.5;color:#bdae93;}
  label{display:block;font-size:.85rem;margin:1rem 0 .3rem;}
  input{width:100%;box-sizing:border-box;padding:.55rem .65rem;border-radius:6px;
    border:1px solid #504945;background:#32302f;color:#ebdbb2;font-size:.95rem;}
  button{margin-top:1.25rem;width:100%;padding:.6rem;border:none;border-radius:6px;
    background:#fb4934;color:#1d2021;font-weight:600;font-size:.95rem;cursor:pointer;}
  .error{color:#fb4934;font-size:.85rem;margin-top:.75rem;}
  .ok{color:#b8bb26;}
"""


def _account_deletion_page(*, error: str | None = None, done: bool = False) -> str:
    body = """
    <h1>Delete your Renar account</h1>
    <p>This starts the same account-deletion process as the in-app option.
    Your account enters a grace period — logging back in during that window
    cancels the deletion. After the grace period, your account and its data
    are permanently removed.</p>
    <form method="post" action="/auth/account-deletion">
      <label for="username">Username or email</label>
      <input id="username" name="username" type="text" autocomplete="username" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Request account deletion</button>
    </form>"""
    if done:
        body = """
    <h1>Deletion requested</h1>
    <p class="ok">Your account is now in its deletion grace period. Logging
    back in before it ends cancels the deletion.</p>"""
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Renar — Delete account</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_ACCOUNT_DELETION_STYLE}</style></head>
<body><div class="card">{body}{error_html}</div></body></html>"""


@router.get("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
def account_deletion_page(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _account_deletion_page()


@router.post("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
def account_deletion_submit(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    ip = client_ip(request)
    try:
        user = _authenticate_for_confirmation(username, password, ip, db)
    except HTTPException as exc:
        # Same generic message regardless of bad username vs. bad password —
        # no account enumeration, matching /auth/login's own error shape.
        return _account_deletion_page(error=exc.detail if isinstance(exc.detail, str) else "Request failed")
    accounts.request_deletion(user, db)
    return _account_deletion_page(done=True)
