#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.364740
Revised: 2026/11/22 01:51:02.364740

Sends transactional e-mail through Brevo: the one place that knows the Brevo
API, shared by the confirmation codes (users/email_confirmation.py) and the
moderation statements of reasons (moderation/mail.py).
"""

import logging

import httpx

from .. import site_settings
from ..config import settings
from ..models import MailStatus

_log = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

# One pooled client, same rationale as users/turnstile.py's http_client:
# reusing connections to Brevo saves a TLS handshake per e-mail.
http_client = httpx.Client(timeout=10)


def deliver(to_address: str, subject: str, html: str, text: str) -> MailStatus:
    """Send one e-mail. Never raises: every failure is logged and returned
    as ``MailStatus.failed`` so the caller can record it."""
    if not settings.brevo_api_key:
        _log.info("e-mail to %s not sent, BREVO_API_KEY unset: %s", to_address, subject)
        return MailStatus.not_configured
    ss = site_settings.current()
    payload = {
        "sender": {"name": ss.email_sender_name, "email": ss.email_sender_address},
        "to": [{"email": to_address}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    try:
        resp = http_client.post(
            BREVO_SEND_URL,
            headers={"api-key": settings.brevo_api_key, "content-type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _log.error(
            "could not send e-mail %r to %s via Brevo: %s %s",
            subject,
            to_address,
            exc.response.status_code,
            exc.response.text,
        )
        return MailStatus.failed
    except httpx.HTTPError:
        _log.exception("could not send e-mail %r to %s via Brevo", subject, to_address)
        return MailStatus.failed
    return MailStatus.sent
