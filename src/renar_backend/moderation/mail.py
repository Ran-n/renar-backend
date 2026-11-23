#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.773957
Revised: 2026/11/22 03:03:52.484987

Builds the moderation e-mails from a ModerationDecision: the statement of
reasons to the affected user (DSA art. 17) and the outcome to each person
who reported the content (DSA art. 16(5)). Wording lives in texts.py.
"""

import html
from dataclasses import dataclass

from ..models import ModerationAction, ModerationDecision
from .texts import text_for

# Which report intro and outcome a reporter gets, by action.
_REPORT_KIND = {
    ModerationAction.comment_removed: "comment",
    ModerationAction.comment_report_dismissed: "comment",
    ModerationAction.review_removed: "review",
    ModerationAction.review_report_dismissed: "review",
    ModerationAction.account_suspended: "profile",
    ModerationAction.account_closed: "profile",
}
_OUTCOME = {
    ModerationAction.comment_removed: "removed",
    ModerationAction.review_removed: "removed",
    ModerationAction.account_suspended: "restricted",
    ModerationAction.account_closed: "restricted",
    ModerationAction.comment_report_dismissed: "none",
    ModerationAction.review_report_dismissed: "none",
}

# Same Gruvbox dark palette as the confirmation e-mail; inline styles and a
# table layout because mail clients ignore <style> blocks and flexbox.
_HTML = """\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:#282828;font-family:Verdana,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0"
             style="max-width:560px;background:#3c3836;border-radius:12px;">
        <tr><td style="padding:28px 32px 0;">
          <span style="font-size:22px;font-weight:bold;color:#fabd2f;">Renar</span>
        </td></tr>
        {rows}
        <tr><td style="padding:8px 32px 28px;"></td></tr>
      </table>
    </td></tr></table>
  </body>
</html>
"""
_P_ROW = '<tr><td style="padding:12px 32px 0;color:#ebdbb2;font-size:15px;line-height:1.5;">{}</td></tr>'
_QUOTE_ROW = (
    '<tr><td style="padding:8px 32px 0;"><div style="border-left:3px solid #fabd2f;padding:8px 12px;'
    'color:#d5c4a1;font-size:14px;line-height:1.5;white-space:pre-wrap;">{}</div></td></tr>'
)


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class _Part:
    text: str
    quote: bool = False


def _render(subject: str, parts: list[_Part]) -> Email:
    rows = "".join((_QUOTE_ROW if p.quote else _P_ROW).format(html.escape(p.text)) for p in parts)
    text = "\n\n".join(p.text for p in parts)
    return Email(subject=subject, text=text, html=_HTML.format(rows=rows))


def _reason_parts(t: dict[str, str], decision: ModerationDecision) -> list[_Part]:
    parts = [_Part(t["reason_label"]), _Part(t[f"reason.{decision.reason}"], quote=True)]
    if decision.note:
        parts += [_Part(t["note_label"]), _Part(decision.note, quote=True)]
    return parts


def user_statement(decision: ModerationDecision, language: str | None, new_username: str = "") -> Email:
    """The statement of reasons to the affected user: what was done, to
    which content, why, whether it followed a report, that no automated
    means were used, and how to contest it."""
    t = text_for(language)
    parts = [
        _Part(t["hello"].format(username=decision.username)),
        _Part(t[f"action.{decision.action}"].format(new_username=new_username)),
    ]
    if decision.content_excerpt:
        parts += [_Part(t["content_label"]), _Part(decision.content_excerpt, quote=True)]
    parts += _reason_parts(t, decision)
    parts += [
        _Part(t["from_report_yes"] if decision.from_report else t["from_report_no"]),
        _Part(t["automated"]),
        _Part(t["contest"]),
        _Part(t["signature"]),
    ]
    return _render(t["subject_user"], parts)


def has_reporter_statement(action: ModerationAction) -> bool:
    """Whether reporters are told the outcome of this action."""
    return action in _OUTCOME


def reporter_statement(decision: ModerationDecision, language: str | None, reporter_name: str) -> Email:
    """The outcome of a report, to the person who sent it."""
    t = text_for(language)
    parts = [
        _Part(t["hello"].format(username=reporter_name)),
        _Part(t[f"report.{_REPORT_KIND[decision.action]}"].format(author=decision.username)),
        _Part(t[f"outcome.{_OUTCOME[decision.action]}"]),
        *_reason_parts(t, decision),
        _Part(t["automated"]),
        _Part(t["contest_reporter"]),
        _Part(t["signature"]),
    ]
    return _render(t["subject_reporter"], parts)
