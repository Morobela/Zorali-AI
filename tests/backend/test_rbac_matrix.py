"""RBAC matrix: what each role (readonly / user / admin / owner) may do.

Runs against the real auth stack (the conftest override is removed) with real
JWTs per role, so both require_role() and the route handlers are exercised.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.rbac import get_current_user
from app.db.models import User
from app.db.session import SessionLocal
from app.main import app

ROLES = ("readonly", "user", "admin", "owner")


def _seed_role_users():
    async def _seed():
        async with SessionLocal() as session:
            async with session.begin():
                for role in ROLES:
                    uid = f"rbac-{role}"
                    if await session.get(User, uid) is None:
                        session.add(User(id=uid, email=f"{uid}@zorali.local", role=role))
    asyncio.run(_seed())


def _headers(role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(f'rbac-{role}', role)}"}


@pytest.fixture()
def rbac_client():
    """Real-auth client with per-role users seeded (projects.owner_id is a FK)."""
    _seed_role_users()
    saved = app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False)
    if saved is not None:
        app.dependency_overrides[get_current_user] = saved


@pytest.mark.parametrize("role,expected", [
    ("readonly", 403),
    ("user", 200),
    ("admin", 200),
    ("owner", 200),
])
def test_project_read_requires_user_or_above(rbac_client, role, expected):
    resp = rbac_client.get("/api/project", headers=_headers(role))
    assert resp.status_code == expected, resp.text


@pytest.mark.parametrize("role,expected", [
    ("readonly", 403),
    ("user", 200),
    ("admin", 200),
    ("owner", 200),
])
def test_project_create_requires_user_or_above(rbac_client, role, expected):
    resp = rbac_client.post(
        "/api/project", json={"name": f"rbac-{role}-proj"}, headers=_headers(role)
    )
    assert resp.status_code == expected, resp.text


@pytest.mark.parametrize("role,expected", [
    ("readonly", 403),
    ("user", 403),      # role gate fires before anything else
    ("admin", 403),     # role passes; CODE_EXECUTION_ENABLED=false gate fires
    ("owner", 403),
])
def test_artifact_run_admin_gate_and_setting_gate(rbac_client, role, expected):
    resp = rbac_client.post("/api/artifacts/nonexistent/run", headers=_headers(role))
    assert resp.status_code == expected, resp.text
    detail = resp.json()["detail"]
    if role in ("readonly", "user"):
        assert "role" in detail.lower()          # rejected by RBAC
    else:
        assert "disabled" in detail.lower()      # rejected by the setting gate


@pytest.mark.parametrize("role", ROLES)
def test_every_authenticated_role_can_get_ws_ticket(rbac_client, role):
    resp = rbac_client.post("/api/ws-ticket", headers=_headers(role))
    assert resp.status_code == 200, resp.text


def test_role_rank_is_enforced_not_just_membership(rbac_client):
    """A token with an unknown role must rank below readonly and be rejected."""
    bogus = {"Authorization": f"Bearer {create_access_token('rbac-user', 'superuser')}"}
    resp = rbac_client.get("/api/project", headers=bogus)
    assert resp.status_code == 403
