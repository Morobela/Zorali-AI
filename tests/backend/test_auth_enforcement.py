"""
Verify that every user-facing route rejects unauthenticated callers and that
the WebSocket handler closes connections that arrive without a valid JWT.

These tests temporarily remove the get_current_user override installed by
conftest.py so the real auth stack runs.
"""
import pytest
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient
from app.main import app
from app.core.rbac import get_current_user


PROTECTED_ROUTES = [
    ("GET", "/api/project"),
    ("POST", "/api/project"),
    ("GET", "/api/files/list?project_id=x"),
    ("GET", "/api/files/search?project_id=x&q=y"),
    ("GET", "/api/memory/search?project_id=x&q=y"),
    ("GET", "/api/artifacts?project_id=x"),
    ("GET", "/api/tools"),
    ("POST", "/api/ws-ticket"),
    ("GET", "/api/skills"),
    ("GET", "/api/inference/energy"),
    ("GET", "/api/providers/status"),
    ("GET", "/api/ollama/health"),
    # A2A task endpoints — agent card stays public, task data must not be
    ("POST", "/a2a/tasks/send"),
    ("GET", "/a2a/tasks"),
]


@pytest.fixture()
def raw_client():
    """Yield a TestClient with real auth, then restore the test override."""
    saved = app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app, raise_server_exceptions=False)
    if saved is not None:
        app.dependency_overrides[get_current_user] = saved


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_protected_route_returns_401_without_token(raw_client, method, path):
    resp = raw_client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, want 401"


def test_ws_chat_rejects_missing_token():
    """WebSocket without token must be closed with policy violation (1008)."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/chat/test-no-token"):
            pass
    assert exc.value.code == 1008


def test_ws_chat_rejects_invalid_ticket():
    """WebSocket with a garbage ticket must be closed with policy violation (1008)."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/chat/test-bad-ticket?ticket=not-a-ticket"):
            pass
    assert exc.value.code == 1008


def test_ws_chat_rejects_legacy_query_jwt():
    """The old ?token=<jwt> path is gone: even a VALID access token in the
    query string must not authenticate a WebSocket."""
    from app.core.auth import create_access_token

    client = TestClient(app)
    jwt = create_access_token("test-user", "owner")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/chat/legacy?token={jwt}"):
            pass
    assert exc.value.code == 1008


def test_demo_login_available_in_local_env(monkeypatch):
    """demo-login must return a token when APP_ENV is local (the default)."""
    monkeypatch.setattr("app.api.auth.settings.app_env", "local")
    client = TestClient(app)
    resp = client.post("/api/auth/demo-login")
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_demo_login_blocked_in_production(monkeypatch):
    """demo-login must return 404 when APP_ENV is production."""
    monkeypatch.setattr("app.api.auth.settings.app_env", "production")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/auth/demo-login")
    assert resp.status_code == 404


def test_health_endpoint_is_public():
    """/api/health must stay public (load-balancer probe)."""
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_a2a_agent_card_is_public():
    """Agent card must be discoverable without auth (A2A discovery spec)."""
    client = TestClient(app)
    resp = client.get("/a2a/.well-known/agent.json")
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "zorali-ai-v1"


# ── Per-user data isolation (Phase 3) ────────────────────────────────────────

from uuid import uuid4


def _auth(client, email):
    """Register a fresh user and return an Authorization header for them."""
    res = client.post("/api/auth/register", json={"email": email, "password": "secret-pass-123"})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_cross_user_project_and_resource_isolation(raw_client):
    """User A owns a project + file + artifact + memory; user B is walled off."""
    a = _auth(raw_client, f"a-{uuid4().hex[:8]}@example.com")
    b = _auth(raw_client, f"b-{uuid4().hex[:8]}@example.com")

    # A creates a project and populates it.
    proj = raw_client.post("/api/project", json={"name": "A-secret"}, headers=a).json()
    pid = proj["id"]

    up = raw_client.post(
        f"/api/files/upload?project_id={pid}",
        files={"file": ("secret.txt", b"alpha bravo charlie secret payload", "text/plain")},
        headers=a,
    )
    assert up.status_code == 202
    file_id = up.json()["id"]

    art = raw_client.post(
        "/api/artifacts", json={"project_id": pid, "name": "spec", "content": "v1"}, headers=a
    ).json()
    artifact_id = art["id"]

    mem = raw_client.post(
        "/api/memory", json={"project_id": pid, "text": "A likes python and fastapi"}, headers=a
    ).json()
    memory_id = mem["id"]

    # ---- B cannot LIST ----
    assert all(p["id"] != pid for p in raw_client.get("/api/project", headers=b).json())
    assert raw_client.get(f"/api/files/list?project_id={pid}", headers=b).status_code == 404
    assert raw_client.get(f"/api/artifacts?project_id={pid}", headers=b).status_code == 404
    assert raw_client.get(f"/api/project/{pid}/chats", headers=b).status_code == 404

    # ---- B cannot READ ----
    assert raw_client.get(f"/api/files/{file_id}/status", headers=b).status_code == 404
    assert raw_client.get(f"/api/artifacts/{artifact_id}", headers=b).status_code == 404

    # ---- B cannot SEARCH ----
    assert raw_client.get(f"/api/files/search?project_id={pid}&q=secret", headers=b).status_code == 404
    # Memory search is namespaced by owner: B sees none of A's memories.
    assert raw_client.get(f"/api/memory/search?project_id={pid}&q=python", headers=b).json() == []

    # ---- B cannot WRITE into A's project ----
    assert raw_client.post(
        f"/api/files/upload?project_id={pid}",
        files={"file": ("evil.txt", b"malicious", "text/plain")}, headers=b,
    ).status_code == 404
    assert raw_client.post(
        "/api/artifacts", json={"project_id": pid, "name": "x", "content": "y"}, headers=b
    ).status_code == 404

    # ---- B cannot DELETE ----
    assert raw_client.delete(f"/api/files/{file_id}", headers=b).status_code == 404
    assert raw_client.delete(f"/api/artifacts/{artifact_id}", headers=b).status_code in (404, 405)
    # A's memory is untouched by B's delete (owner-scoped → deletes nothing).
    assert raw_client.delete(f"/api/memory/{memory_id}", headers=b).json() == {"deleted": False}

    # ---- A still has full access (nothing was corrupted) ----
    assert any(p["id"] == pid for p in raw_client.get("/api/project", headers=a).json())
    assert raw_client.get(f"/api/files/list?project_id={pid}", headers=a).status_code == 200
    assert raw_client.get(f"/api/artifacts/{artifact_id}", headers=a).status_code == 200
    a_hits = raw_client.get(f"/api/files/search?project_id={pid}&q=secret", headers=a)
    assert a_hits.status_code == 200 and a_hits.json()
    assert raw_client.get(f"/api/memory/search?project_id={pid}&q=python", headers=a).json()


def test_updating_another_users_artifact_is_404(raw_client):
    a = _auth(raw_client, f"a2-{uuid4().hex[:8]}@example.com")
    b = _auth(raw_client, f"b2-{uuid4().hex[:8]}@example.com")
    proj = raw_client.post("/api/project", json={"name": "A2"}, headers=a).json()
    art = raw_client.post(
        "/api/artifacts", json={"project_id": proj["id"], "name": "s", "content": "v1"}, headers=a
    ).json()
    resp = raw_client.put(f"/api/artifacts/{art['id']}", json={"content": "hacked"}, headers=b)
    assert resp.status_code == 404
    # A's artifact is unchanged: still a single version.
    got = raw_client.get(f"/api/artifacts/{art['id']}", headers=a).json()
    assert len(got["versions"]) == 1 and got["versions"][0]["content"] == "v1"
