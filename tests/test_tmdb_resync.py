#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/18 22:40:40.143841
Revised: 2026/08/26 08:54:18.227430

resync_tmdb_metadata is the only background job that revisits a tracked
title regardless of watch status — check_new_episodes/check_upcoming_films
both permanently stop polling once a show is dropped/ended or a film is
released, so a title's poster/backdrop could otherwise go stale forever.
"""

from fastapi import HTTPException

from renar_backend.database import SessionLocal
from renar_backend.models import Title
from renar_backend.social.notifier import resync_tmdb_metadata


def _add(client, headers, **kwargs) -> dict:
    payload = {"title": "Placeholder", "status": "watching"} | kwargs
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _fake_fetch(poster_path: str):
    def fetch(tmdb_id: int) -> dict:
        return {"poster_path": poster_path}

    return fetch


def test_resync_refreshes_poster_for_completed_show(client, alice):
    _, headers = alice
    _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="completed")

    db = SessionLocal()
    try:
        n = resync_tmdb_metadata(
            db, fetch_show=_fake_fetch("/new-poster.jpg"), fetch_film=_fake_fetch("/unused.jpg"), pace_seconds=0
        )
        assert n == 1
    finally:
        db.close()

    out = client.get("/media", headers=headers).json()
    assert out[0]["poster_url"].endswith("/new-poster.jpg")


def test_resync_refreshes_poster_for_dropped_film(client, alice):
    _, headers = alice
    _add(client, headers, media_type="film", title="Old Movie", tmdb_id=998, status="dropped")

    db = SessionLocal()
    try:
        n = resync_tmdb_metadata(
            db, fetch_show=_fake_fetch("/unused.jpg"), fetch_film=_fake_fetch("/updated-poster.jpg"), pace_seconds=0
        )
        assert n == 1
    finally:
        db.close()

    out = client.get("/media", headers=headers).json()
    assert out[0]["poster_url"].endswith("/updated-poster.jpg")


def test_resync_survives_fetch_failure(client, alice):
    _, headers = alice
    _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")

    def broken_fetch(tmdb_id: int) -> dict:
        raise RuntimeError("TMDB down")

    db = SessionLocal()
    try:
        n = resync_tmdb_metadata(db, fetch_show=broken_fetch, fetch_film=broken_fetch, pace_seconds=0)
        assert n == 0
    finally:
        db.close()


def test_resync_delinks_dead_tmdb_id_on_404(client, alice):
    _, headers = alice
    _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")

    def not_found_fetch(tmdb_id: int) -> dict:
        raise HTTPException(status_code=404, detail="Not found on TMDB")

    db = SessionLocal()
    try:
        n = resync_tmdb_metadata(db, fetch_show=not_found_fetch, fetch_film=not_found_fetch, pace_seconds=0)
        assert n == 0
        title = db.query(Title).filter_by(title="Dark").one()
        assert title.tmdb_id is None
    finally:
        db.close()


def test_resync_skips_untracked_title(client, alice):
    _, headers = alice
    # no library entries created at all
    db = SessionLocal()
    try:

        def fail_if_called(tmdb_id: int) -> dict:
            raise AssertionError("should not fetch anything for an empty library")

        n = resync_tmdb_metadata(db, fetch_show=fail_if_called, fetch_film=fail_if_called, pace_seconds=0)
        assert n == 0
    finally:
        db.close()
