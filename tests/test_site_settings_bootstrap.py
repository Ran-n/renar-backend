#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/23 12:58:39.191315
Revised: 2026/11/23 12:58:39.191315

The site_settings row is created by the first request that reads it. Two
first requests at once used to end in a 500 for the one that lost the insert.
"""

from renar_backend.database import SessionLocal
from renar_backend.models import SiteSettings
from renar_backend.site_settings import get_site_settings


def test_first_read_creates_the_row():
    with SessionLocal() as db:
        assert get_site_settings(db).id == 1
    with SessionLocal() as db:
        assert db.query(SiteSettings).count() == 1


def test_losing_the_creation_race_reads_the_winners_row(monkeypatch):
    with SessionLocal() as db, SessionLocal() as other:
        real_begin_nested = db.begin_nested

        def other_request_first():
            get_site_settings(other).invite_only = True
            other.commit()
            return real_begin_nested()

        monkeypatch.setattr(db, "begin_nested", other_request_first)
        assert get_site_settings(db).invite_only is True
        db.commit()  # the session is still usable
    with SessionLocal() as db:
        assert db.query(SiteSettings).count() == 1
