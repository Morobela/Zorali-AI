"""Assistant-parity features: conversation list, regenerate, stop generation,
and per-project custom instructions."""
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import create_access_token
from app.db.repositories import repo

client = TestClient(app)

_WS_TOKEN = create_access_token("test-user", "owner")


def _project(name):
    return client.post("/api/project", json={"name": name}).json()


# ── Conversation (session) list ──────────────────────────────────────────────

def test_project_sessions_lists_conversations_newest_first():
    p = _project("sessions-proj")
    pid = p["id"]
    s1, s2 = f"s1-{uuid4().hex[:6]}", f"s2-{uuid4().hex[:6]}"
    asyncio.run(repo.add_chat_message(pid, s1, "user", "first conversation opener"))
    asyncio.run(repo.add_chat_message(pid, s1, "assistant", "reply one"))
    asyncio.run(repo.add_chat_message(pid, s2, "user", "second conversation opener"))

    rows = client.get(f"/api/project/{pid}/sessions").json()
    assert [r["session_id"] for r in rows] == [s2, s1]
    by_id = {r["session_id"]: r for r in rows}
    assert by_id[s1]["message_count"] == 2
    assert by_id[s1]["preview"].startswith("first conversation")
    assert by_id[s2]["message_count"] == 1
    assert rows[0]["last_at"] >= rows[1]["last_at"]


def test_project_sessions_cross_user_is_404():
    p = _project("sessions-isolated")
    # Another account's token cannot list this project's conversations.
    from app.core.rbac import get_current_user
    saved = app.dependency_overrides.pop(get_current_user, None)
    try:
        raw = TestClient(app, raise_server_exceptions=False)
        other = raw.post(
            "/api/auth/register",
            json={"email": f"other-{uuid4().hex[:8]}@example.com", "password": "secret-pass-123"},
        ).json()["access_token"]
        res = raw.get(f"/api/project/{p['id']}/sessions", headers={"Authorization": f"Bearer {other}"})
        assert res.status_code == 404
    finally:
        if saved is not None:
            app.dependency_overrides[get_current_user] = saved


# ── Custom instructions ──────────────────────────────────────────────────────

def test_patch_project_sets_custom_instructions():
    p = _project("instructions-proj")
    res = client.patch(f"/api/project/{p['id']}", json={"system_prompt": "Always answer in French."})
    assert res.status_code == 200
    assert res.json()["system_prompt"] == "Always answer in French."
    # Persisted and returned on subsequent reads
    listed = client.get("/api/project").json()
    got = next(x for x in listed if x["id"] == p["id"])
    assert got["system_prompt"] == "Always answer in French."


def test_custom_instructions_are_threaded_into_prompt(monkeypatch):
    captured = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = messages
        yield "ok"

    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("instructions-chat")
    client.patch(f"/api/project/{p['id']}", json={"system_prompt": "Respond like a pirate."})

    with client.websocket_connect(f"/ws/chat/instr-{uuid4().hex[:6]}?token={_WS_TOKEN}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "hello"})
        while ws.receive_json().get("type") != "done":
            pass

    sys_msgs = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert any("Respond like a pirate." in m for m in sys_msgs)


# ── Regenerate ───────────────────────────────────────────────────────────────

def test_regenerate_replaces_last_assistant_message(monkeypatch):
    calls = {"n": 0}

    async def fake_stream(messages, **kwargs):
        calls["n"] += 1
        yield f"answer-{calls['n']}"

    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("regen-proj")
    session = f"regen-{uuid4().hex[:6]}"

    with client.websocket_connect(f"/ws/chat/{session}?token={_WS_TOKEN}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "tell me a joke"})
        while ws.receive_json().get("type") != "done":
            pass
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "tell me a joke", "regenerate": True})
        while ws.receive_json().get("type") != "done":
            pass

    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    roles = [m["role"] for m in history]
    # One user turn, one (regenerated) assistant turn — not two of each.
    assert roles == ["user", "assistant"]
    assert history[-1]["content"] == "answer-2"


# ── Stop generation ──────────────────────────────────────────────────────────

def test_stop_interrupts_streaming(monkeypatch):
    async def slow_stream(messages, **kwargs):
        for i in range(50):
            yield f"tok{i} "
            await asyncio.sleep(0.05)

    monkeypatch.setattr("app.api.chat.stream_llm", slow_stream)
    p = _project("stop-proj")
    session = f"stop-{uuid4().hex[:6]}"

    with client.websocket_connect(f"/ws/chat/{session}?token={_WS_TOKEN}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "long story please"})
        first = ws.receive_json()
        assert first["type"] == "token"
        ws.send_json({"mode": "stop"})
        done = None
        tokens_after_stop = 0
        for _ in range(60):
            msg = ws.receive_json()
            if msg["type"] == "done":
                done = msg
                break
            tokens_after_stop += 1
        assert done is not None
        assert done["stopped"] is True
        # Generation was cut off well before all 50 tokens streamed.
        assert tokens_after_stop < 40

        # The connection stays usable after a stop.
        ws.send_json({"mode": "task", "project_id": p["id"], "message": "/help"})
        follow_up = ws.receive_json()
        assert follow_up["type"] == "task_result"

    # The partial answer was persisted for the session.
    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[-1]["content"].startswith("tok0")


def test_stop_with_nothing_streaming_is_harmless():
    with client.websocket_connect(f"/ws/chat/idle-{uuid4().hex[:6]}?token={_WS_TOKEN}") as ws:
        ws.send_json({"mode": "stop"})
        ws.send_json({"mode": "task", "project_id": "default", "message": "/help"})
        msg = ws.receive_json()
        assert msg["type"] == "task_result"
