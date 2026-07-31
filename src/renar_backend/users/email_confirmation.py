#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 12:30:00.000000
Revised: 2026/07/21 09:51:07.781622

Registration/email-change confirmation codes — see routers/auth.py's
/auth/confirm-email and /auth/resend-confirmation, and models.py's
EmailConfirmationCode. Built to close the ranking-inflation gap a captcha
alone doesn't: a human can still hand-register throwaway accounts past
Turnstile, but not accounts nobody can receive a real email at (see
docs/backlog.md's "Real email confirmation on registration" entry and
routers/stats.py._compute_ranking, which only counts email_confirmed users).

Code storage mirrors users/auth.py's password hashing (bcrypt, not
plaintext — see InviteCode's docstring in models.py for why a plaintext
token is fine there but not here: this guards account takeover, not just
registration gating). Sending follows tmdb/tmdb_store.py::warm_title_translations'
BackgroundTasks idiom — the DB write (new code row) happens synchronously so
a caller can rely on it existing, but the network call to Brevo is
backgrounded so an outage never blocks register/login/resend.
"""

import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import httpx
from sqlalchemy.orm import Session

from .. import site_settings
from ..config import settings
from ..models import EmailConfirmationCode, User, utcnow

_log = logging.getLogger(__name__)

CODE_LENGTH = 6
MAX_ATTEMPTS = 8  # past this, a code is treated as burned regardless of expires_at
# Grace period (routers/auth.py's login) and cleanup age (cleanup_unconfirmed_accounts
# below) are both admin-tunable now — see site_settings.py's email_confirmation_grace_days
# / unconfirmed_account_cleanup_days. Grace should stay shorter than cleanup so nobody
# is deleted before ever being blocked at login, but that's an admin-panel convention,
# not an enforced invariant here.

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

# One pooled client, same rationale as users/turnstile.py's http_client:
# reusing connections to Brevo saves a TLS handshake per confirmation email.
_http_client = httpx.Client(timeout=10)

_SUBJECTS = {
    "register": "Confirm your Renar account",
    "change_authorize": "Confirm your Renar email change",
    "change_confirm": "Confirm your new Renar email address",
}

_INTROS = {
    "register": "Welcome to Renar! Use the code below to confirm your account.",
    "change_authorize": (
        "We received a request to change the email address on your Renar account. "
        "Use the code below to authorize the change."
    ),
    "change_confirm": "Use the code below to confirm your new email address on Renar.",
}
_DEFAULT_INTRO = "Use the code below to confirm your email on Renar."

# Hosted in the (public) Ran-n/media repo, not this one — renar-frontend is
# private, so a raw.githubusercontent.com link to an asset in it 404s for
# anyone without repo access, including Brevo/the recipient's mail client.
# Static, not the drawing-mark animation (renar_1.gif): Gmail's web renderer
# ignores a GIF's loop-count metadata and always loops it forever, so the
# one-shot "draws once" effect isn't achievable there. True PNG alpha (not
# renar_0.png's boxed icon) — a hosted PNG's transparency renders fine in
# Gmail, unlike a data: URI, which Gmail strips outright.
_LOGO_URL = "https://raw.githubusercontent.com/Ran-n/media/main/companies/renar_2.png"

# Gruvbox dark, same palette as the app (branding/themes.py) — inline styles
# and a table layout because email clients don't reliably support <style>
# blocks or flexbox/grid.
_HTML_TEMPLATE = """\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:#282828;font-family:Verdana,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0"
             style="max-width:480px;background:#3c3836;border-radius:12px;">
        <tr><td style="padding:36px 32px 4px;text-align:center;">
          <img src="{logo_url}" width="96" height="96" alt="" style="display:block;margin:0 auto;">
        </td></tr>
        <tr><td style="padding:8px 32px 0;text-align:center;">
          <span style="font-size:26px;font-weight:bold;color:#fabd2f;letter-spacing:1px;">Renar</span>
        </td></tr>
        <tr><td style="padding:16px 32px 0;text-align:center;color:#ebdbb2;font-size:15px;line-height:1.5;">
          {intro}
        </td></tr>
        <tr><td style="padding:24px 32px;text-align:center;">
          <span style="display:inline-block;background:#282828;border:1px solid #504945;border-radius:8px;
                       padding:14px 24px;font-family:'Courier New',monospace;font-size:30px;font-weight:bold;
                       letter-spacing:8px;color:#fabd2f;">{code}</span>
        </td></tr>
        <tr><td style="padding:0 32px 32px;text-align:center;color:#a89984;font-size:13px;line-height:1.5;">
          This code expires in {ttl} minutes. If you didn't request this, you can safely ignore this email.
        </td></tr>
      </table>
    </td></tr></table>
  </body>
</html>
"""


def generate_code() -> str:
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()


def verify_code(code: str, code_hash: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode(), code_hash.encode())
    except ValueError:
        return False


def send_confirmation_email(to_address: str, code: str, language: str, purpose: str) -> None:
    """If BREVO_API_KEY is unset, log the would-be email instead of sending —
    safe default until a verified sending domain exists (see backlog). This
    is the only wiring needed to flip real sending on later."""
    if not settings.brevo_api_key:
        _log.info(
            "email confirmation code for %s (purpose=%s, lang=%s, not sent — BREVO_API_KEY unset): %s",
            to_address,
            purpose,
            language,
            code,
        )
        return
    ss = site_settings.current()
    intro = _INTROS.get(purpose, _DEFAULT_INTRO)
    payload = {
        "sender": {"name": ss.email_sender_name, "email": ss.email_sender_address},
        "to": [{"email": to_address}],
        "subject": _SUBJECTS.get(purpose, "Confirm your Renar email"),
        "htmlContent": _HTML_TEMPLATE.format(
            intro=intro, code=code, ttl=ss.confirmation_code_ttl_minutes, logo_url=_LOGO_URL
        ),
        "textContent": (
            f"{intro}\n\nYour confirmation code is: {code}\n\n"
            f"This code expires in {ss.confirmation_code_ttl_minutes} minutes."
        ),
    }
    try:
        resp = _http_client.post(
            BREVO_SEND_URL,
            headers={"api-key": settings.brevo_api_key, "content-type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _log.error(
            "could not send confirmation email to %s via Brevo: %s %s",
            to_address,
            exc.response.status_code,
            exc.response.text,
        )
    except httpx.HTTPError:
        _log.exception("could not send confirmation email to %s via Brevo", to_address)


def create_and_send_code(db: Session, user: User, purpose: str, target_email: str, background_tasks) -> None:
    """Invalidates any prior un-consumed code of this purpose for `user`,
    inserts a new one, commits, and schedules the send. Synchronous DB write
    (the caller/tests can rely on the row existing immediately after this
    returns) — only the network call to Brevo is backgrounded."""
    db.query(EmailConfirmationCode).filter(
        EmailConfirmationCode.user_id == user.id,
        EmailConfirmationCode.purpose == purpose,
        EmailConfirmationCode.consumed_at.is_(None),
    ).update({EmailConfirmationCode.consumed_at: utcnow()}, synchronize_session=False)

    code = generate_code()
    db.add(
        EmailConfirmationCode(
            user_id=user.id,
            code_hash=hash_code(code),
            purpose=purpose,
            expires_at=utcnow() + timedelta(minutes=site_settings.current().confirmation_code_ttl_minutes),
        )
    )
    db.commit()
    background_tasks.add_task(send_confirmation_email, target_email, code, user.language, purpose)


# ---------------------------------------------------------------------------
# Resend throttle — same sliding-window deque pattern as
# users/security.py::check_login_allowed, gated by the same admin toggle.
# ---------------------------------------------------------------------------

_MINUTE = 60.0
RESEND_WINDOW_MINUTES = 5
RESEND_LIMIT = 3

_resend_attempts: dict[str, deque[float]] = defaultdict(deque)


def _prune(dq: deque[float], cutoff: float) -> None:
    while dq and dq[0] < cutoff:
        dq.popleft()


def check_resend_allowed(username: str) -> int | None:
    """Returns seconds to wait if this account is over the resend limit, else None."""
    if not settings.abuse_guard_enabled:
        return None
    now = time.time()
    key = username.strip().lower()
    dq = _resend_attempts[key]
    _prune(dq, now - RESEND_WINDOW_MINUTES * _MINUTE)
    if len(dq) >= RESEND_LIMIT:
        return int(dq[0] + RESEND_WINDOW_MINUTES * _MINUTE - now) + 1
    return None


def note_resend(username: str) -> None:
    if not settings.abuse_guard_enabled:
        return
    _resend_attempts[username.strip().lower()].append(time.time())


# ---------------------------------------------------------------------------
# Periodic cleanup — see task_runs.py / social/notifier.py.start_periodic_tasks
# ---------------------------------------------------------------------------


def cleanup_unconfirmed_accounts(db: Session) -> int:
    """Delete email_confirmed=False users older than unconfirmed_account_cleanup_days, so a
    never-confirmed signup doesn't squat a username/email forever (uniqueness
    is checked at registration regardless of confirmation status). Returns
    the number of rows deleted. Reuses accounts.delete_account — a plain
    db.delete(user) would trip over the FK-safe ordering that helper already
    handles (comments, notifications, etc. don't cascade at the DB level)."""
    from . import accounts  # local import: avoids a cycle at module load

    cutoff = datetime.now(UTC) - timedelta(days=site_settings.current().unconfirmed_account_cleanup_days)
    stale = (
        db.query(User)
        .filter(
            User.email_confirmed.is_(False),
            User.created_at < cutoff,
        )
        .all()
    )
    count = len(stale)
    for user in stale:
        accounts.delete_account(user, db)
    return count
