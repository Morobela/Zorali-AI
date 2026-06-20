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


def test_ws_chat_rejects_invalid_token():
    """WebSocket with a garbage token must be closed with policy violation (1008)."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/chat/test-bad-token?token=not.a.jwt"):
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
