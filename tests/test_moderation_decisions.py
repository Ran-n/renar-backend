#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:03.854054
Revised: 2026/11/22 03:03:52.676738

Moderation decisions (moderation/decisions.py and the admin pages that call
it): every moderation action records one decision and e-mails the statement
of reasons to the user and the outcome to the reporters (DSA art. 16(5),
17); a failed e-mail is recorded and shown; decisions are purged 6 months
after their measure ends; every app language has the e-mail wording.
"""

from datetime import timedelta

import httpx
import pytest

from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    CommentReport,
    MailStatus,
    ModerationAction,
    ModerationDecision,
    ModerationReason,
    ReviewReport,
    ReviewWhitelist,
    UserReport,
    utcnow,
)
from renar_backend.moderation import decisions, mail, texts
from renar_backend.users import mailer

FILM = {"media_type": "film", "tmdb_id": 949}


@pytest.fixture
def sent(monkeypatch):
    """Fake mail server: records (to, subject, text) and answers ``status``."""
    box = {"status": MailStatus.sent, "mails": []}

    def deliver(to_address, subject, html, text):
        box["mails"].append((to_address, subject, text))
        return box["status"]

    monkeypatch.setattr(decisions.mailer, "deliver", deliver)
    return box


@pytest.fixture
def carol(make_user):
    return make_user("carol")


def _comment(client, headers, text="rude words") -> dict:
    r = client.post("/comments", json={"media_type": "film", "title": "Heat", "text": text}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _review(client, user, headers) -> dict:
    with SessionLocal() as db:
        db.add(ReviewWhitelist(user_id=user["id"]))
        db.commit()
    r = client.post(
        "/media/reviews",
        params={**FILM, "title": "Heat"},
        json={"text": "A genuine masterpiece.", "rating": 95},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _decisions() -> list[ModerationDecision]:
    with SessionLocal() as db:
        return db.query(ModerationDecision).order_by(ModerationDecision.id).all()


def _count(model) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


def _post(client, admin, path, **data):
    return client.post(f"/admin{path}", data=data, headers=admin, follow_redirects=False)


# ---------- comments ----------


def test_deleting_a_reported_comment_records_and_mails_both_sides(client, admin_enabled, alice, bob, sent):
    _, alice_headers = alice
    _, bob_headers = bob
    long_text = "x" * 400
    comment = _comment(client, alice_headers, long_text)
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204

    r = _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="harassment", details="Insults bob")
    assert r.status_code == 303

    [d] = _decisions()
    assert d.action is ModerationAction.comment_removed
    assert d.reason is ModerationReason.harassment
    assert d.note == "Insults bob"
    assert d.username == "alice" and d.target_id == comment["id"]
    assert d.from_report is True
    assert len(d.content_excerpt) == decisions.EXCERPT_CHARS and d.content_excerpt.endswith("…")
    assert d.measure_ended_at is not None
    assert d.email_status is MailStatus.sent
    assert d.reporters_notified == 1
    to_alice, to_bob = sent["mails"]
    assert to_alice[0] == "alice@example.com" and "moderation decision" in to_alice[1]
    assert "We removed one of your comments." in to_alice[2]
    assert "legal@renar.app within 6 months" in to_alice[2]
    assert "followed a report" in to_alice[2]
    assert to_bob[0] == "bob@example.com" and "outcome of your report" in to_bob[1]
    assert "a comment by alice" in to_bob[2] and "removed the content" in to_bob[2]
    assert _count(Comment) == 0


def test_deleting_a_comment_needs_a_breach_reason(client, admin_enabled, alice, sent):
    _, headers = alice
    comment = _comment(client, headers)
    assert _post(client, admin_enabled, f"/comments/{comment['id']}/delete").status_code == 422
    assert _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="bogus").status_code == 422
    no_breach = _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="no_breach")
    assert no_breach.status_code == 422
    assert _count(Comment) == 1 and _decisions() == [] and sent["mails"] == []


def test_unreported_comment_removal_says_own_initiative(client, admin_enabled, alice, sent):
    _, headers = alice
    comment = _comment(client, headers)
    _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="spam")
    [d] = _decisions()
    assert d.from_report is False and d.reporters_notified == 0
    [(_, _, text)] = sent["mails"]
    assert "own initiative" in text


def test_dismissing_comment_reports_tells_only_the_reporters(client, admin_enabled, alice, bob, carol, sent):
    _, alice_headers = alice
    comment = _comment(client, alice_headers, "fine words")
    for _, headers in (bob, carol):
        client.post(f"/comments/{comment['id']}/report", headers=headers)

    r = _post(client, admin_enabled, f"/comments/{comment['id']}/dismiss-reports", reason="no_breach")
    assert r.status_code == 303

    [d] = _decisions()
    assert d.action is ModerationAction.comment_report_dismissed
    assert d.email_status is MailStatus.not_needed
    assert d.reporters_notified == 2
    assert sorted(m[0] for m in sent["mails"]) == ["bob@example.com", "carol@example.com"]
    assert all("took no action" in m[2] for m in sent["mails"])
    assert _count(Comment) == 1 and _count(CommentReport) == 0


def test_dismissing_needs_reports_and_the_no_breach_reason(client, admin_enabled, alice, bob, sent):
    _, alice_headers = alice
    comment = _comment(client, alice_headers)
    path = f"/comments/{comment['id']}/dismiss-reports"
    assert _post(client, admin_enabled, path, reason="no_breach").status_code == 404
    client.post(f"/comments/{comment['id']}/report", headers=bob[1])
    assert _post(client, admin_enabled, path, reason="spam").status_code == 422
    assert _post(client, admin_enabled, "/comments/9999/dismiss-reports", reason="no_breach").status_code == 404
    assert _decisions() == []


# ---------- reviews ----------


def test_deleting_and_dismissing_reported_reviews(client, admin_enabled, alice, bob, sent):
    alice_user, alice_headers = alice
    _, bob_headers = bob
    review = _review(client, alice_user, alice_headers)
    client.post(f"/media/reviews/{review['id']}/report", headers=bob_headers)

    dismissed = _post(client, admin_enabled, f"/reported-reviews/{review['id']}/dismiss", reason="no_breach")
    assert dismissed.status_code == 303
    assert _count(ReviewReport) == 0
    again = _post(client, admin_enabled, f"/reported-reviews/{review['id']}/dismiss", reason="no_breach")
    assert again.status_code == 404
    assert _post(client, admin_enabled, "/reported-reviews/9999/dismiss", reason="no_breach").status_code == 404

    client.post(f"/media/reviews/{review['id']}/report", headers=bob_headers)
    removed = _post(client, admin_enabled, f"/reported-reviews/{review['id']}/delete", reason="spam")
    assert removed.status_code == 303

    first, second = _decisions()
    assert first.action is ModerationAction.review_report_dismissed
    assert second.action is ModerationAction.review_removed and second.content_excerpt == "A genuine masterpiece."
    assert "We removed one of your reviews." in sent["mails"][1][2]
    assert "a review by alice" in sent["mails"][2][2]


# ---------- accounts ----------


def test_ban_records_an_open_decision_that_unban_ends(client, admin_enabled, alice, bob, sent):
    alice_user, _ = alice
    _, bob_headers = bob
    client.post(f"/users/{alice_user['id']}/report", json={"reason": "spam bot"}, headers=bob_headers)
    assert _count(UserReport) == 1

    assert _post(client, admin_enabled, f"/users/{alice_user['id']}/ban").status_code == 422
    assert _post(client, admin_enabled, f"/users/{alice_user['id']}/ban", reason="spam").status_code == 303
    [d] = _decisions()
    assert d.action is ModerationAction.account_suspended and d.measure_ended_at is None
    assert d.from_report is True and d.reporters_notified == 1
    assert _count(UserReport) == 0
    assert "suspended your account" in sent["mails"][0][2]
    assert "restricted the account" in sent["mails"][1][2]

    assert _post(client, admin_enabled, f"/users/{alice_user['id']}/unban").status_code == 303
    [d] = _decisions()
    assert d.measure_ended_at is not None


def test_closing_an_account_mails_the_address_it_had(client, admin_enabled, alice, sent):
    alice_user, _ = alice
    r = _post(client, admin_enabled, f"/users/{alice_user['id']}/delete", reason="illegal_content")
    assert r.status_code == 303
    [d] = _decisions()
    assert d.action is ModerationAction.account_closed and d.user_id is None and d.username == "alice"
    assert d.email_status is MailStatus.sent
    [(to, _, text)] = sent["mails"]
    assert to == "alice@example.com" and "closed your account" in text


def test_deleting_an_account_on_request_records_nothing(client, admin_enabled, alice, sent):
    alice_user, _ = alice
    assert _post(client, admin_enabled, f"/users/{alice_user['id']}/delete").status_code == 303
    assert _decisions() == [] and sent["mails"] == []


def test_username_reset_as_a_measure_names_the_new_username(client, admin_enabled, alice, sent):
    alice_user, _ = alice
    uid = alice_user["id"]
    assert _post(client, admin_enabled, f"/users/{uid}/edit", username="fixed").status_code == 303
    assert _decisions() == []  # a plain edit isn't moderation
    r = _post(client, admin_enabled, f"/users/{uid}/edit", username="renamed", reason="harassment")
    assert r.status_code == 303
    [d] = _decisions()
    assert d.action is ModerationAction.username_reset and d.content_excerpt == "fixed"
    assert "Your new username is renamed." in sent["mails"][0][2]
    assert _post(client, admin_enabled, f"/users/{uid}/edit", username="x2", reason="no_breach").status_code == 422


def test_withdrawn_review_rights_end_when_restored(client, admin_enabled, alice, sent):
    alice_user, _ = alice
    uid = alice_user["id"]
    assert _post(client, admin_enabled, f"/users/{uid}/unwhitelist-review").status_code == 303
    assert _decisions() == []
    assert _post(client, admin_enabled, f"/users/{uid}/unwhitelist-review", reason="spam").status_code == 303
    [d] = _decisions()
    assert d.action is ModerationAction.review_rights_withdrawn and d.measure_ended_at is None
    assert _post(client, admin_enabled, f"/users/{uid}/whitelist-review").status_code == 303
    [d] = _decisions()
    assert d.measure_ended_at is not None


# ---------- failures, the Decisions page and resending ----------


def test_failed_statement_is_recorded_shown_and_can_be_resent(client, admin_enabled, alice, sent):
    _, headers = alice
    sent["status"] = MailStatus.failed
    comment = _comment(client, headers)
    _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="spam")
    [d] = _decisions()
    assert d.email_status is MailStatus.failed

    page = client.get("/admin/decisions", headers=admin_enabled)
    assert page.status_code == 200
    assert "Comment removed" in page.text and "Failed" in page.text and "Send again" in page.text

    sent["status"] = MailStatus.sent
    assert _post(client, admin_enabled, f"/decisions/{d.id}/resend").status_code == 303
    [d] = _decisions()
    assert d.email_status is MailStatus.sent
    assert _post(client, admin_enabled, f"/decisions/{d.id}/resend").status_code == 409
    assert _post(client, admin_enabled, "/decisions/9999/resend").status_code == 404


def test_statement_for_a_deleted_account_cant_be_resent(client, admin_enabled, alice, sent):
    alice_user, _ = alice
    sent["status"] = MailStatus.failed
    _post(client, admin_enabled, f"/users/{alice_user['id']}/delete", reason="spam")
    [d] = _decisions()
    page = client.get("/admin/decisions", headers=admin_enabled).text
    assert "(deleted)" in page and "Send again" not in page
    assert _post(client, admin_enabled, f"/decisions/{d.id}/resend").status_code == 409


def test_decisions_page_empty_and_pickers_on_admin_pages(client, admin_enabled, alice, bob):
    alice_user, alice_headers = alice
    assert "No decisions yet" in client.get("/admin/decisions", headers=admin_enabled).text
    comment = _comment(client, alice_headers)
    client.post(f"/comments/{comment['id']}/report", headers=bob[1])
    comments = client.get("/admin/comments", headers=admin_enabled).text
    assert 'name="reason" required' in comments and 'value="harassment"' in comments
    assert "Dismiss reports" in comments and 'value="no_breach"' in comments
    user_page = client.get(f"/admin/users/{alice_user['id']}", headers=admin_enabled).text
    assert "Not a moderation measure" in user_page
    assert "Moderation Decisions" in client.get("/admin", headers=admin_enabled).text


def test_without_a_mail_key_the_statement_is_marked_not_sent(client, admin_enabled, alice, monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "")
    _, headers = alice
    comment = _comment(client, headers)
    _post(client, admin_enabled, f"/comments/{comment['id']}/delete", reason="spam")
    [d] = _decisions()
    assert d.email_status is MailStatus.not_configured
    assert "no mail key" in client.get("/admin/decisions", headers=admin_enabled).text


# ---------- purge ----------


def test_purge_deletes_only_decisions_ended_over_6_months_ago(alice):
    alice_user, _ = alice
    now = utcnow()
    with SessionLocal() as db:
        for ended in (now - timedelta(days=200), now - timedelta(days=10), None):
            db.add(
                ModerationDecision(
                    action=ModerationAction.account_suspended,
                    reason=ModerationReason.spam,
                    moderator="root",
                    user_id=alice_user["id"],
                    username="alice",
                    created_at=now - timedelta(days=300),
                    measure_ended_at=ended,
                    email_status=MailStatus.sent,
                    reporters_notified=0,
                    from_report=False,
                )
            )
        db.commit()
    from renar_backend.social.notifier import purge_expired_decisions_once

    assert purge_expired_decisions_once() == 1
    assert len(_decisions()) == 2


# ---------- wording and the mailer ----------


def test_every_language_has_every_string():
    keys = set(texts.EN)
    for code, table in texts.TEXTS.items():
        assert set(table) == keys, code
    assert {f"reason.{r}" for r in ModerationReason} <= keys
    assert texts.text_for("xx") is texts.EN and texts.text_for(None) is texts.EN


@pytest.mark.parametrize("language", sorted(texts.TEXTS))
def test_statements_render_in_every_language_and_escape_content(language):
    decision = ModerationDecision(
        action=ModerationAction.comment_removed,
        reason=ModerationReason.spam,
        note="<b>note</b>",
        username="alice",
        content_excerpt="<script>x</script>",
        from_report=True,
    )
    user_mail = mail.user_statement(decision, language)
    assert "&lt;script&gt;" in user_mail.html and "<script>" not in user_mail.html
    assert "<script>x</script>" in user_mail.text and "legal@renar.app" in user_mail.text
    reporter_mail = mail.reporter_statement(decision, language, "bob")
    assert "alice" in reporter_mail.text and reporter_mail.subject == texts.TEXTS[language]["subject_reporter"]


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "boom"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=self)


def test_mailer_reports_sent_failed_and_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "")
    assert mailer.deliver("a@example.com", "s", "<p>h</p>", "t") is MailStatus.not_configured
    monkeypatch.setattr(settings, "brevo_api_key", "key")
    monkeypatch.setattr(mailer.http_client, "post", lambda *a, **kw: _Response(200))
    assert mailer.deliver("a@example.com", "s", "<p>h</p>", "t") is MailStatus.sent
    monkeypatch.setattr(mailer.http_client, "post", lambda *a, **kw: _Response(500))
    assert mailer.deliver("a@example.com", "s", "<p>h</p>", "t") is MailStatus.failed

    def _down(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(mailer.http_client, "post", _down)
    assert mailer.deliver("a@example.com", "s", "<p>h</p>", "t") is MailStatus.failed
