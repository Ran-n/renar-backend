#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:29:43.281408
Revised: 2026/11/10 11:04:48.287418

Locust load profile: a rough mirror of a logged-in user's traffic mix once
the app is open (health/status checks, own-profile lookups, stats), weighted
toward the cheap, frequently-polled endpoints. Driven headlessly by
tests/integration/test_load.py against a live_server (isolated Postgres
schema) — not meant to be pointed at a real deployment.

Write tasks added 2026-09-02:
  - post_comment  (weight 1) — POST /comments; less frequent than reads
  - rate_item     (weight 2) — PATCH /media/{id}; rating an item is a common
                               mid-session action
  - add_to_library (weight 1) — POST /media with a unique synthetic title;
                                infrequent but exercises the create path
  Import (POST /import) is intentionally excluded: it requires a multipart
  file upload whose bytes must pass content-based detection (renar JSON or
  TVTime CSV structure); constructing a minimal valid file inline would be
  brittle and mask real detection latency. Cover it in integration tests.

Total weight breakdown: reads 11 (4+3+2+1+1), writes 4 (2+1+1) → writes are
~27 % of simulated traffic, a realistic browse-plus-occasional-edit session.
"""

import random
import uuid

from locust import HttpUser, between, task

LOAD_TEST_PASSWORD = "LoadTest123!"

# A well-known TMDB title used as a shared comment/rating target across all
# simulated users. Inception (movie, tmdb_id=27205) is present on TMDB and
# any frontend test fixture that loads catalog data will have seen it.
_SEED_TMDB_ID = 27205
_SEED_TITLE = "Inception"
_SEED_MEDIA_TYPE = "film"  # models.MediaType: film | tv_show


class RenarUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        username = f"loadtest_{uuid.uuid4().hex[:12]}"
        self.client.post(
            "/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": LOAD_TEST_PASSWORD},
            name="/auth/register",
        )
        # Test-server-only endpoint (see renar_backend._test_server): bypasses
        # real email delivery so login works without a mail server in the loop.
        self.client.post(f"/_itest/confirm_email/{username}", name="/_itest/confirm_email/[username]")
        r = self.client.post(
            "/auth/login",
            data={"username": username, "password": LOAD_TEST_PASSWORD},
            name="/auth/login",
        )
        token = r.json().get("access_token") if r.status_code == 200 else None
        self.auth_headers = {"Authorization": f"Bearer {token}"} if token else {}

        # Pre-seed one library entry so rate_item always has a valid item_id.
        # 409 is expected if two users race to add the same title — ignore it.
        seed = self.client.post(
            "/media",
            headers=self.auth_headers,
            json={"media_type": _SEED_MEDIA_TYPE, "title": _SEED_TITLE, "tmdb_id": _SEED_TMDB_ID},
            name="/media [on_start seed]",
        )
        self.seed_item_id = seed.json().get("id") if seed.status_code == 201 else None

    @task(4)
    def health(self):
        self.client.get("/health")

    @task(3)
    def me(self):
        self.client.get("/auth/me", headers=self.auth_headers)

    @task(2)
    def library(self):
        self.client.get("/media", headers=self.auth_headers)

    @task(1)
    def stats(self):
        self.client.get("/stats", headers=self.auth_headers)

    @task(1)
    def registration_status(self):
        # Deliberately unauthenticated — exercises the public path too.
        self.client.get("/auth/registration-status")

    # ------------------------------------------------------------------ writes

    @task(1)
    def post_comment(self):
        """POST /comments — exercises comment creation under load.

        Uses the seed title so the Title row is guaranteed to exist (it was
        created in on_start). Weight 1: commenting is less frequent than
        browsing but still a first-class write path worth stressing.
        """
        self.client.post(
            "/comments",
            headers=self.auth_headers,
            json={
                "media_type": _SEED_MEDIA_TYPE,
                "tmdb_id": _SEED_TMDB_ID,
                "title": _SEED_TITLE,
                "text": f"Load-test comment {uuid.uuid4().hex[:8]}",
            },
            name="/comments [post]",
        )

    @task(2)
    def rate_item(self):
        """PATCH /media/{id} — exercises rating writes under load.

        Randomises the rating on every call to avoid identical-update
        short-circuits and to stress the trigger that maintains the community
        aggregate columns on Title. Weight 2: rating is a common mid-session
        action (users rate right after marking something watched).
        """
        if self.seed_item_id is None:
            return
        rating = random.randint(1, 100)
        self.client.patch(
            f"/media/{self.seed_item_id}",
            headers=self.auth_headers,
            json={"rating": rating},
            name="/media/[id] [patch rating]",
        )

    @task(1)
    def add_to_library(self):
        """POST /media — exercises the full create-library-entry path.

        Each call uses a unique synthetic title to avoid 409 conflicts.
        Weight 1: adding new titles is infrequent relative to viewing/editing.
        """
        unique_title = f"Load Test Film {uuid.uuid4().hex[:8]}"
        self.client.post(
            "/media",
            headers=self.auth_headers,
            json={"media_type": "film", "title": unique_title},
            name="/media [add]",
        )
