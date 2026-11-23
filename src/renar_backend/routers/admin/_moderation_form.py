#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.963653
Revised: 2026/11/22 01:51:02.963653

The reason picker every moderation action in the admin panel carries, and
the check of what it submits (moderation/reasons.py has the lists).
"""

import html

from fastapi import HTTPException

from ...models import ModerationAction, ModerationReason
from ...moderation.reasons import BREACH_REASONS, REASON_LABELS, reason_fits

# Shown as the first option where the action can also be routine admin work
# (a username fix, an account deleted on request): picking it records no
# decision and sends no e-mail.
NOT_MODERATION = ""
_NOT_MODERATION_LABEL = "Not a moderation measure"


def _reason_select(first_option: str, required: str) -> str:
    options = "".join(f'<option value="{r}">{html.escape(REASON_LABELS[r])}</option>' for r in BREACH_REASONS)
    return (
        f'<select class="action-input reason-select" name="reason"{required}>{first_option}{options}</select>'
        '<input class="action-input" type="text" name="details" maxlength="1000"'
        ' placeholder="Facts for the user (optional)">'
    )


def measure_fields() -> str:
    """A required <select name="reason"> of breach reasons plus a free-text
    note, for a form that always applies a measure."""
    return _reason_select('<option value="" disabled selected>Reason&hellip;</option>', " required")


def optional_measure_fields() -> str:
    """The same picker led by "Not a moderation measure", for an action that
    can also be routine admin work. Not `required`: an empty first option
    would count as unpicked."""
    return _reason_select(f'<option value="{NOT_MODERATION}">{_NOT_MODERATION_LABEL}</option>', "")


def dismissal_fields() -> str:
    """Hidden "no breach" reason plus a free-text note, for a dismiss form."""
    return (
        f'<input type="hidden" name="reason" value="{ModerationReason.no_breach}">'
        '<input class="action-input" type="text" name="details" maxlength="1000"'
        ' placeholder="Why it breaks no rule (optional)">'
    )


def parse_reason(action: ModerationAction, value: str) -> ModerationReason:
    """The submitted reason, or 422 when it isn't one or doesn't fit the
    action (a measure needs a breach; a dismissal is always "no breach")."""
    try:
        reason = ModerationReason(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Pick a reason for this decision") from None
    if not reason_fits(action, reason):
        raise HTTPException(status_code=422, detail="That reason doesn't fit this decision")
    return reason


def optional_reason(action: ModerationAction, value: str) -> ModerationReason | None:
    """Like parse_reason, but "Not a moderation measure" gives None."""
    return None if value == NOT_MODERATION else parse_reason(action, value)
