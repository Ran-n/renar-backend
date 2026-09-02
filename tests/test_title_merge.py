#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/19 19:11:30.977386
Revised: 2026/09/02 10:58:18.793037

merge_titles folds a duplicate, still-unmatched Title into the Title that
already holds the tmdb_id/tvdb_id it was about to claim (see
catalog/titles.py's backfill_title_tmdb_id/backfill_title_tvdb_id and
docs/backlog.md's "unmergeable Title row" entry). test_unmatched_title_retry.py
covers the end-to-end retry path that triggers a merge; this file exercises
merge_titles directly against every table it touches, including the
per-table collision rules a same-tmdb_id race can produce.
"""

import pytest
from sqlalchemy import inspect

from renar_backend.catalog.titles import merge_titles
from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    Episode,
    EpisodeRatingAggregate,
    LibraryEntry,
    MediaType,
    Title,
    TmdbCache,
    WatchStatus,
)

pytestmark = pytest.mark.regression


def _make_titles(db, **loser_overrides):
    winner = Title(media_type=MediaType.film, tmdb_id=949, title="Heat", title_key=None)
    loser = Title(media_type=MediaType.film, tmdb_id=None, title="Heat (raw import name)", title_key="heat-raw")
    for k, v in loser_overrides.items():
        setattr(loser, k, v)
    db.add_all([winner, loser])
    db.flush()
    return winner, loser


def test_merge_moves_a_solo_library_entry_and_updates_rating_totals(client, alice):
    user, _ = alice
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        entry = LibraryEntry(user_id=user["id"], title_id=loser.id, status=WatchStatus.completed, rating=80)
        db.add(entry)
        db.flush()

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        db.refresh(entry)
        assert entry.title_id == winner.id
        assert winner.rating_sum == 80
        assert winner.rating_count == 1
        assert inspect(loser).deleted
    finally:
        db.rollback()
        db.close()


def test_merge_drops_the_duplicate_entry_when_the_same_user_tracks_both(client, alice):
    user, _ = alice
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        kept = LibraryEntry(user_id=user["id"], title_id=winner.id, status=WatchStatus.completed, rating=90)
        dropped = LibraryEntry(user_id=user["id"], title_id=loser.id, status=WatchStatus.want_to_watch, rating=50)
        db.add_all([kept, dropped])
        db.flush()
        dropped_id = dropped.id
        db.refresh(winner)  # picks up rating_sum/count from the insert trigger

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        assert db.get(LibraryEntry, dropped_id) is None
        db.refresh(kept)
        assert kept.title_id == winner.id
        # dropped entry's rating must NOT be folded in: winner keeps its own
        assert winner.rating_sum == 90
        assert winner.rating_count == 1
    finally:
        db.rollback()
        db.close()


def test_merge_episodes_winner_wins_on_collision_moves_the_rest(client):
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        # colliding episode: winner's own synced copy must survive
        db.add(Episode(title_id=winner.id, season=1, episode_number=1, name="Winner's Copy"))
        db.add(Episode(title_id=loser.id, season=1, episode_number=1, name="Loser's Copy"))
        # non-colliding episode: must move over intact
        moved = Episode(title_id=loser.id, season=1, episode_number=2, name="Only On Loser")
        db.add(moved)
        db.flush()
        moved_id = moved.id

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        remaining = db.query(Episode).filter(Episode.title_id == winner.id).all()
        by_key = {(e.season, e.episode_number): e.name for e in remaining}
        assert by_key[(1, 1)] == "Winner's Copy"
        assert by_key[(1, 2)] == "Only On Loser"
        assert db.get(Episode, moved_id).title_id == winner.id
    finally:
        db.rollback()
        db.close()


def test_merge_sums_episode_rating_aggregates_on_collision(client):
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        db.add(EpisodeRatingAggregate(title_id=winner.id, season=1, episode=1, rating_sum=100, rating_count=2))
        db.add(EpisodeRatingAggregate(title_id=loser.id, season=1, episode=1, rating_sum=70, rating_count=1))
        db.flush()

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        agg = (
            db.query(EpisodeRatingAggregate)
            .filter(EpisodeRatingAggregate.title_id == winner.id, EpisodeRatingAggregate.season == 1)
            .one()
        )
        assert agg.rating_sum == 170
        assert agg.rating_count == 3
    finally:
        db.rollback()
        db.close()


def test_merge_reassigns_comments(client, alice):
    user, _ = alice
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        comment = Comment(user_id=user["id"], title_id=loser.id, text="Great film")
        db.add(comment)
        db.flush()
        comment_id = comment.id

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        assert db.get(Comment, comment_id).title_id == winner.id
    finally:
        db.rollback()
        db.close()


def test_merge_unions_genres_and_fills_metadata_gaps(client):
    from renar_backend.catalog.titles import resolve_genres

    db = SessionLocal()
    try:
        winner, loser = _make_titles(db, poster_url="/loser-poster.jpg", runtime_minutes=170)
        winner.runtime_minutes = 120  # winner already has its own: must survive the merge
        winner.genre_rows = resolve_genres(db, ["Crime"])
        loser.genre_rows = resolve_genres(db, ["Crime", "Drama"])
        db.flush()

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        db.refresh(winner)
        assert sorted(winner.genres) == ["Crime", "Drama"]
        assert winner.poster_url == "/loser-poster.jpg"  # winner had none: gap filled
        assert winner.runtime_minutes == 120  # winner already had its own: not overwritten
    finally:
        db.rollback()
        db.close()


def test_merge_drops_the_duplicate_tmdb_cache_entry_on_collision(client):
    db = SessionLocal()
    try:
        winner, loser = _make_titles(db)
        db.add(TmdbCache(title_id=winner.id, kind="details", season=-1, language="en", payload={"from": "winner"}))
        db.add(TmdbCache(title_id=loser.id, kind="details", season=-1, language="en", payload={"from": "loser"}))
        moved = TmdbCache(title_id=loser.id, kind="credits", season=-1, language="en", payload={})
        db.add(moved)
        db.flush()
        moved_id = moved.id

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        remaining = db.query(TmdbCache).filter(TmdbCache.title_id == winner.id).all()
        details = [c for c in remaining if c.kind == "details"]
        assert len(details) == 1
        assert details[0].payload == {"from": "winner"}
        assert db.get(TmdbCache, moved_id).title_id == winner.id
    finally:
        db.rollback()
        db.close()
