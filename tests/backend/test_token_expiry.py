"""Expired tokens must be rejected — lifetime math alone is not enough."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.auth import ALGORITHM
from app.core.config import settings
from app.core.rbac import get_current_user
from app.main import app


def _expired_token(token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "test-user",
        "role": "owner",
        "type": token_type,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),   # expired an hour ago
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


@pytest.fixture()
def raw_client():
    saved = app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False)
    if saved is not None:
        app.dependency_overrides[get_current_user] = saved


def test_expired_access_token_is_rejected(raw_client):
    resp = raw_client.get(
        "/api/project", headers={"Authorization": f"Bearer {_expired_token()}"}
    )
    assert resp.status_code == 401


def test_expired_refresh_token_cannot_refresh(raw_client):
    resp = raw_client.post(
        "/api/auth/refresh", json={"refresh_token": _expired_token("refresh")}
    )
    assert resp.status_code == 401


def test_expired_token_cannot_mint_ws_ticket(raw_client):
    resp = raw_client.post(
        "/api/ws-ticket", headers={"Authorization": f"Bearer {_expired_token()}"}
    )
    assert resp.status_code == 401
