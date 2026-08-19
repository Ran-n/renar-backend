#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:29:43.281408
Revised: 2026/08/18 17:29:43.281408

Locust load profile: a rough mirror of a logged-in user's traffic mix once
the app is open (health/status checks, own-profile lookups, stats), weighted
toward the cheap, frequently-polled endpoints. Driven headlessly by
tests/integration/test_load.py against a live_server (isolated Postgres
schema) — not meant to be pointed at a real deployment.
"""

import uuid

from locust import HttpUser, between, task

LOAD_TEST_PASSWORD = "LoadTest123!"


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
