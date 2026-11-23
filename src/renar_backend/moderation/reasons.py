#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.558602
Revised: 2026/11/22 01:51:02.558602

The admin panel's labels for moderation actions and reasons, and which
reasons fit which action. English only: the admin panel is English.
"""

from ..models import ModerationAction, ModerationReason

REASON_LABELS: dict[ModerationReason, str] = {
    ModerationReason.illegal_content: "Illegal content",
    ModerationReason.no_rights: "No right to share it (e.g. copyright)",
    ModerationReason.harassment: "Harassment, threats, insults or impersonation",
    ModerationReason.hate_or_violence: "Hate speech, violence or self-harm",
    ModerationReason.child_sexual_content: "Sexual content involving minors",
    ModerationReason.spam: "Spam, advertising or bulk accounts",
    ModerationReason.circumvention: "Circumventing anti-abuse measures",
    ModerationReason.scraping: "Automated scraping",
    ModerationReason.disruption: "Disrupting the service",
    ModerationReason.no_breach: "No breach found",
}

ACTION_LABELS: dict[ModerationAction, str] = {
    ModerationAction.comment_removed: "Comment removed",
    ModerationAction.review_removed: "Review removed",
    ModerationAction.account_suspended: "Account suspended",
    ModerationAction.account_closed: "Account closed",
    ModerationAction.username_reset: "Username changed",
    ModerationAction.review_rights_withdrawn: "Review rights withdrawn",
    ModerationAction.comment_report_dismissed: "Comment report dismissed",
    ModerationAction.review_report_dismissed: "Review report dismissed",
}

# A dismissed report found no breach; every other action is a measure and
# needs a breach as its reason.
DISMISSAL_ACTIONS = frozenset({ModerationAction.comment_report_dismissed, ModerationAction.review_report_dismissed})
BREACH_REASONS = tuple(r for r in ModerationReason if r is not ModerationReason.no_breach)


def reason_fits(action: ModerationAction, reason: ModerationReason) -> bool:
    """A dismissal's reason is always "no breach"; a measure's never is."""
    return (reason is ModerationReason.no_breach) == (action in DISMISSAL_ACTIONS)
