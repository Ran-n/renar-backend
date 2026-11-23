#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 11:53:53.885574
Revised: 2026/11/22 05:15:08.941540

Cloudflare Access check on the admin path (users/cf_access.py).

With ``CF_ACCESS_TEAM_DOMAIN`` and ``CF_ACCESS_AUD`` set, a request under
``ADMIN_PATH`` needs Access's signed ``Cf-Access-Jwt-Assertion`` header; one
without a valid token gets the same 404 as an unknown path, with a warning
and no abuse strike. Unset (dev), nothing changes. Tokens here are signed
with an RSA key made for the test, and the JWKS lookup is patched to return
its public half, so no request leaves the machine.
"""

import logging
import time
import types

import jwt
import pytest
from conftest import ADMIN_API_TOKEN
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from renar_backend.config import Settings, settings
from renar_backend.database import SessionLocal
from renar_backend.main import app, install_middleware
from renar_backend.models import BannedIP, Strike
from renar_backend.users import cf_access

pytestmark = pytest.mark.regression

TEAM = "renar-test.cloudflareaccess.com"
AUD = "4714c1358e65fe4b408ad6d432a5f878f08194bdb4752441fd56faefa9b2b6f2"
ISSUER = f"https://{TEAM}"
LOGGER = "renar_backend.users.cf_access"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(*, key=_KEY, aud=AUD, iss=ISSUER, exp_in=300, drop=(), algorithm="RS256", **extra) -> str:
    now = int(time.time())
    claims = {"aud": [aud], "iss": iss, "iat": now, "exp": now + exp_in, "email": "operator@example.com", **extra}
    for name in drop:
        del claims[name]
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "test-key"})


def with_token(token: str | None = None) -> dict[str, str]:
    return {cf_access.HEADER: token if token is not None else make_token()}


@pytest.fixture
def access_on(monkeypatch):
    """Access configured, and the JWKS lookup answering with the test key."""
    monkeypatch.setattr(settings, "cf_access_team_domain", TEAM)
    monkeypatch.setattr(settings, "cf_access_aud", AUD)
    monkeypatch.setattr(
        jwt.PyJWKClient,
        "get_signing_key_from_jwt",
        lambda self, token: types.SimpleNamespace(key=_KEY.public_key()),
    )


def strikes_and_bans() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(Strike).count(), db.query(BannedIP).count()


# ---------- off (dev): nothing changes ----------


def test_unset_admin_path_works_without_a_header(client, admin_enabled):
    assert cf_access.enabled() is False
    assert client.get("/admin/login").status_code == 200
    assert client.get("/admin", headers=admin_enabled, follow_redirects=False).status_code == 200


def test_unset_never_looks_up_keys(client, admin_enabled, monkeypatch):
    def boom(self, token):
        raise AssertionError("the keys must not be fetched when Access is off")

    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", boom)
    assert client.get("/admin/login", headers=with_token("anything")).status_code == 200


# ---------- on: a valid token passes ----------


def test_valid_token_reaches_the_login_page(client, admin_enabled, access_on):
    assert client.get("/admin/login", headers=with_token()).status_code == 200


def test_valid_token_plus_session_reaches_the_panel(client, admin_enabled, access_on):
    r = client.get("/admin", headers={**admin_enabled, **with_token()}, follow_redirects=False)
    assert r.status_code == 200


def test_aud_given_as_a_plain_string_is_accepted(client, admin_enabled, access_on):
    now = int(time.time())
    token = jwt.encode({"aud": AUD, "iss": ISSUER, "exp": now + 300}, _KEY, algorithm="RS256")
    assert client.get("/admin/login", headers=with_token(token)).status_code == 200


def test_token_expired_within_the_clock_skew_is_accepted(client, admin_enabled, access_on):
    assert client.get("/admin/login", headers=with_token(make_token(exp_in=-30))).status_code == 200


def test_keys_are_looked_up_at_the_team_certs_url(access_on, monkeypatch):
    seen = []
    real = cf_access._keys_client

    def spy(url):
        seen.append(url)
        return real(url)

    monkeypatch.setattr(cf_access, "_keys_client", spy)
    cf_access.verify_access_jwt(make_token())
    assert seen == [f"https://{TEAM}/cdn-cgi/access/certs"]


# ---------- on: everything else is a 404, logged, with no strike ----------

_REFUSED = [
    pytest.param(lambda: None, "missing", id="missing-header"),
    pytest.param(lambda: "", "missing", id="empty-header"),
    pytest.param(lambda: make_token(aud="another-application"), "wrong aud", id="wrong-aud"),
    pytest.param(lambda: make_token(iss="https://evil.cloudflareaccess.com"), "wrong iss", id="wrong-iss"),
    pytest.param(lambda: make_token(exp_in=-3600), "expired", id="expired"),
    pytest.param(lambda: make_token(key=_OTHER_KEY), "bad signature", id="signed-by-another-key"),
    pytest.param(lambda: make_token(drop=("exp",)), "missing claim", id="no-exp"),
    pytest.param(lambda: make_token(drop=("aud",)), "missing claim", id="no-aud"),
    pytest.param(
        lambda: make_token(key="shared-secret-shared-secret-32-b", algorithm="HS256"), "invalid token", id="hs256"
    ),
    pytest.param(lambda: "not.a.jwt", "invalid token", id="garbage"),
]


@pytest.mark.parametrize(("token", "reason"), _REFUSED)
def test_refused_token_is_a_404_logged_without_a_strike(client, admin_enabled, access_on, caplog, token, reason):
    value = token()
    headers = {} if value is None else {cf_access.HEADER: value}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        r = client.get("/admin/login", headers=headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
    assert f"Cloudflare Access token {reason}" in caplog.text
    assert "testclient" in caplog.text  # the client IP
    if value:
        assert value not in caplog.text  # never the token
    assert strikes_and_bans() == (0, 0)


def test_refusal_looks_exactly_like_an_unknown_path(client, admin_enabled, access_on):
    refused = client.get("/admin/login")
    unknown = client.get("/no-such-path-anywhere")
    assert (refused.status_code, refused.json()) == (unknown.status_code, unknown.json())


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin"),
        ("GET", "/admin/"),
        ("GET", "/admin/login"),
        ("POST", "/admin/login"),
        ("GET", "/admin/users"),
        ("GET", "/admin/settings"),
        ("POST", "/admin/app-releases"),
        ("POST", "/admin/logout"),
    ],
)
def test_every_admin_route_is_gated_even_with_a_valid_session(client, admin_enabled, access_on, method, path):
    assert client.request(method, path, headers=admin_enabled, follow_redirects=False).status_code == 404


def test_upload_route_with_api_token_but_no_access_header_is_404(client, admin_enabled, access_on):
    bearer = {"Authorization": f"Bearer {ADMIN_API_TOKEN}"}
    assert client.post("/admin/app-releases", headers=bearer).status_code == 404
    # with the Access header the same request gets past the gate (and then
    # fails validation: no file was sent)
    assert client.post("/admin/app-releases", headers={**bearer, **with_token()}).status_code == 422


def test_moved_admin_path_is_the_one_gated(client, admin_enabled, access_on, monkeypatch):
    monkeypatch.setattr(settings, "admin_path", "/panel-x7k2")
    assert cf_access.is_admin_path("/panel-x7k2") and cf_access.is_admin_path("/panel-x7k2/login")
    assert not cf_access.is_admin_path("/panel-x7k2-other")
    assert not cf_access.is_admin_path("/admin/login")


def test_many_refusals_never_ban(admin_enabled, access_on):
    """With the abuse guard on: a stale tab retrying must not strike or ban."""
    guarded = FastAPI()
    guarded.router.routes.extend(app.router.routes)
    install_middleware(guarded, abuse_guard=True)
    with TestClient(guarded) as guarded_client:
        statuses = {guarded_client.get("/admin/login").status_code for _ in range(40)}
    assert statuses == {404}
    assert strikes_and_bans() == (0, 0)


# ---------- keys unavailable: fail closed ----------


def test_key_fetch_failure_is_503_and_logged(client, admin_enabled, access_on, monkeypatch, caplog):
    def unreachable(self, token):
        raise jwt.exceptions.PyJWKClientConnectionError("certs URL unreachable")

    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", unreachable)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        r = client.get("/admin/login", headers=with_token())
    assert r.status_code == 503
    assert r.json() == {"detail": "Admin access check unavailable"}
    assert "Cloudflare Access keys unavailable" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    assert strikes_and_bans() == (0, 0)


def test_token_naming_an_unknown_key_is_404_not_503(client, admin_enabled, access_on, monkeypatch, caplog):
    """The keys were fetched but none matches: a forged token, not an outage."""

    def no_such_key(self, token):
        raise jwt.PyJWKClientError('Unable to find a signing key that matches: "forged"')

    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", no_such_key)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        r = client.get("/admin/login", headers=with_token())
    assert r.status_code == 404
    assert "Cloudflare Access token bad signature" in caplog.text


# ---------- only the admin path ----------


@pytest.mark.parametrize("path", ["/health", "/app-releases/latest?platform=android-arm64-v8a", "/", "/robots.txt"])
def test_other_paths_are_never_checked(client, access_on, monkeypatch, path):
    def boom(token):
        raise AssertionError(f"{path} must not be checked")

    monkeypatch.setattr(cf_access, "verify_access_jwt", boom)
    assert client.get(path).status_code != 503


def test_health_is_200_with_access_on(client, access_on):
    assert client.get("/health").status_code == 200


# ---------- settings ----------


def test_config_both_empty_loads():
    loaded = Settings(cf_access_team_domain="", cf_access_aud="")
    assert (loaded.cf_access_team_domain, loaded.cf_access_aud) == ("", "")


def test_config_both_set_loads_and_normalises_the_domain():
    loaded = Settings(cf_access_team_domain=f" https://{TEAM}/ ", cf_access_aud=f" {AUD}\n")
    assert (loaded.cf_access_team_domain, loaded.cf_access_aud) == (TEAM, AUD)


@pytest.mark.parametrize("only", [{"cf_access_team_domain": TEAM}, {"cf_access_aud": AUD}])
def test_config_only_one_set_stops_the_boot(only):
    with pytest.raises(ValidationError, match="set both CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD, or neither"):
        Settings(**{"cf_access_team_domain": "", "cf_access_aud": "", **only})


def test_garbage_token_is_malformed_before_any_key_fetch(monkeypatch):
    """A token whose header can't be read is refused as "malformed" by the
    key lookup itself (the fixture above fakes that lookup, so this calls the
    real one; PyJWT rejects the header before fetching any keys)."""
    monkeypatch.setattr(settings, "cf_access_team_domain", TEAM)
    with pytest.raises(cf_access.AccessDenied, match="malformed"):
        cf_access._signing_key("not.a.jwt")
