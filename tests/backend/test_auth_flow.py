"""
Register → login → refresh flow against the real auth stack (the conftest
get_current_user override is removed for these tests).
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.core.rbac import get_current_user


@pytest.fixture()
def raw_client():
    saved = app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False)
    if saved is not None:
        app.dependency_overrides[get_current_user] = saved


def _register(client, email, password="secret-pass-123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def test_register_login_refresh_and_protected_access(raw_client):
    email = f"alice-{uuid4().hex[:8]}@example.com"

    res = _register(raw_client, email)
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "user"
    assert body["access_token"] and body["refresh_token"]

    # Duplicate registration is rejected
    assert _register(raw_client, email).status_code == 409

    # Login returns a fresh token pair
    res = raw_client.post("/api/auth/login", json={"email": email, "password": "secret-pass-123"})
    assert res.status_code == 200
    tokens = res.json()

    # Wrong password is rejected
    res = raw_client.post("/api/auth/login", json={"email": email, "password": "wrong-pass-000"})
    assert res.status_code == 401

    # Access token opens protected routes
    res = raw_client.get("/api/project", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 200

    # A refresh token must NOT work as an access token
    res = raw_client.get("/api/project", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert res.status_code == 401

    # ...and an access token must NOT work as a refresh token
    res = raw_client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert res.status_code == 401

    # Refresh issues a new working access token
    res = raw_client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200
    new_access = res.json()["access_token"]
    res = raw_client.get("/api/project", headers={"Authorization": f"Bearer {new_access}"})
    assert res.status_code == 200


def test_register_validation(raw_client):
    assert _register(raw_client, "not-an-email").status_code == 422
    assert _register(raw_client, f"short-{uuid4().hex[:8]}@example.com", "tiny").status_code == 422


def test_login_email_is_case_insensitive(raw_client):
    email = f"case-{uuid4().hex[:8]}@example.com"
    assert _register(raw_client, email).status_code == 201
    res = raw_client.post("/api/auth/login", json={"email": email.upper(), "password": "secret-pass-123"})
    assert res.status_code == 200


def test_token_lifetimes_follow_settings(monkeypatch):
    from app.core import auth as core_auth
    from app.core.config import settings

    monkeypatch.setattr(core_auth.settings, "jwt_access_minutes", 5)
    monkeypatch.setattr(core_auth.settings, "jwt_refresh_days", 2)

    access = core_auth.create_access_token("someone", "user")
    refresh = core_auth.create_refresh_token("someone", "user")
    a = jwt.decode(access, settings.secret_key, algorithms=[core_auth.ALGORITHM])
    r = jwt.decode(refresh, settings.secret_key, algorithms=[core_auth.ALGORITHM])
    assert a["exp"] - a["iat"] == 5 * 60
    assert a["type"] == "access"
    assert r["exp"] - r["iat"] == 2 * 24 * 3600
    assert r["type"] == "refresh"


def test_refresh_with_deleted_account_fails(raw_client):
    token = None
    from app.core.auth import create_refresh_token
    token = create_refresh_token("no-such-user-id", "user")
    res = raw_client.post("/api/auth/refresh", json={"refresh_token": token})
    assert res.status_code == 401
