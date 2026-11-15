#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:10.374454
Revised: 2026/11/13 15:35:10.374454

Small leftover edge paths: admin session/login guards, the per-request
episode cache, next-episode lookup when the stored position is stale, the
unmatched-title retry losing its tmdb_id claim, reviewing a known title by
tmdb_id alone, and import status for a job that already finished.
"""

from datetime import timedelta

import jwt
import pytest
from _race_helpers import commit_elsewhere

from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.models import (
    Episode,
    ImportJob,
    LibraryEntry,
    MediaType,
    ReviewWhitelist,
    Title,
    User,
    prefetch_episode_cache,
    utcnow,
)
from renar_backend.social import notifier
from renar_backend.users import admin_session


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# admin_session
# ---------------------------------------------------------------------------


def test_verify_login_refuses_when_the_panel_is_not_configured(client):
    assert admin_session.admin_configured() is False
    assert admin_session.verify_login("admin", "pw", "123456") is False


def test_read_session_rejects_a_token_for_another_username(client, admin_enabled):
    token = admin_session.issue_session(settings.admin_username)
    claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"], audience=admin_session.AUDIENCE)
    forged = jwt.encode({**claims, "sub": "someone-else"}, settings.secret_key, algorithm="HS256")

    assert admin_session.read_session(token) == settings.admin_username
    assert admin_session.read_session(forged) is None


# ---------------------------------------------------------------------------
# episode cache / next-episode lookup (models.py)
# ---------------------------------------------------------------------------


def _show_with_entry(db, *, current=(None, None)) -> LibraryEntry:
    user = User(username="viewer", email="viewer@example.com", password_hash="x")
    title = Title(media_type=MediaType.tv_show, tmdb_id=4242, title="Dark")
    db.add_all([user, title])
    db.flush()
    db.add_all([
        Episode(title_id=title.id, season=1, episode_number=1, name="Secrets"),
        Episode(title_id=title.id, season=1, episode_number=2, name="Lies"),
    ])
    entry = LibraryEntry(user_id=user.id, title_id=title.id, current_season=current[0], current_episode=current[1])
    db.add(entry)
    db.flush()
    return entry


def test_prefetch_episode_cache_skips_titles_already_cached(db):
    entry = _show_with_entry(db)
    prefetch_episode_cache(db, [entry.title_id])
    cached = db.info["episode_cache_by_title"][entry.title_id]

    statements = []

    from sqlalchemy import event

    @event.listens_for(db, "do_orm_execute")
    def _count(state):
        statements.append(state.statement)

    prefetch_episode_cache(db, [entry.title_id, None])

    assert statements == []
    assert db.info["episode_cache_by_title"][entry.title_id] is cached


def test_episodes_of_a_detached_entry_are_empty(db):
    entry = _show_with_entry(db)
    db.expunge(entry)

    assert entry._episodes == []


def test_next_episode_falls_back_to_the_first_when_position_is_unknown_to_the_catalog(db):
    entry = _show_with_entry(db, current=(5, 9))  # not in the synced catalog

    assert (entry._next_episode_row.season, entry._next_episode_row.episode_number) == (1, 1)


# ---------------------------------------------------------------------------
# notifier.retry_unmatched_titles
# ---------------------------------------------------------------------------


def test_retry_unmatched_titles_uses_injected_matchers_and_skips_a_lost_claim(db, monkeypatch):
    commit_elsewhere(Title(media_type=MediaType.tv_show, title="Unmatched Show", title_key="unmatched show"))
    searched = []
    # the backfill runs but the row still doesn't carry the tmdb_id afterwards,
    # as when another writer claimed it first and nothing could be merged
    monkeypatch.setattr(notifier, "backfill_title_tmdb_id", lambda *a, **kw: None)

    fixed = notifier.retry_unmatched_titles(
        db,
        search_tv=lambda name: searched.append(name) or {"id": 555, "name": "Matched Show"},
        search_movie=lambda name, year: pytest.fail("not a film"),
        find_by_tvdb=lambda tvdb_id: pytest.fail("no tvdb id"),
        fetch_show=lambda *a, **kw: pytest.fail("nothing to refresh"),
        fetch_film=lambda *a, **kw: pytest.fail("nothing to refresh"),
        pace_seconds=0,
    )

    assert fixed == 0
    assert searched == ["Unmatched Show"]
    assert db.query(Title).filter(Title.tmdb_id == 555).count() == 0


# ---------------------------------------------------------------------------
# reviews by tmdb_id alone
# ---------------------------------------------------------------------------


def test_review_by_tmdb_id_alone_targets_the_known_title(client, alice):
    user, headers = alice
    commit_elsewhere(ReviewWhitelist(user_id=user["id"]))
    (title_id,) = commit_elsewhere(Title(media_type=MediaType.film, tmdb_id=949, title="Heat"))

    r = client.post(
        "/media/reviews",
        params={"media_type": "film", "tmdb_id": 949},
        json={"text": "Still holds up.", "rating": 90},
        headers=headers,
    )

    assert r.status_code == 201, r.text
    db = SessionLocal()
    try:
        assert db.query(Title).filter(Title.tmdb_id == 949).one().id == title_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# import status from a finished job row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "stage"),
    [(None, "Done"), ("TV Time file is not a zip", "Failed")],
)
def test_import_status_reports_a_finished_job(client, alice, error, stage):
    user, headers = alice
    summary = {"added": 3} if error is None else None
    commit_elsewhere(
        ImportJob(
            user_id=user["id"],
            kind="tvtime",
            finished=True,
            error=error,
            summary=summary,
            updated_at=utcnow() - timedelta(minutes=5),
        )
    )

    body = client.get("/import/status", headers=headers).json()

    assert body == {
        "stage": stage,
        "finished": True,
        "error": error,
        "summary": summary,
        "done": 0,
        "total": 0,
        "kind": "tvtime",
    }
