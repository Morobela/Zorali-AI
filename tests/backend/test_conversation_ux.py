"""Conversation UX parity (Phase 4).

- chat_sessions rows are created with the first message; the sessions list
  comes from the new table (title + preview + aggregates), newest first.
- One-shot title generation after the first assistant reply; reused, never
  regenerated, never clobbering a user rename.
- Rename/delete endpoints are owner-scoped (404 for non-owners).
- Server-side chat search (ILIKE) is owner-scoped.
- Edit & resend replaces the last user/assistant exchange in the DB.
- <think> parser: closed/multiple/unclosed blocks; stored assistant
  messages carry no chain of thought.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.repositories import repo
from app.main import app
from conftest import ws_ticket

client = TestClient(app)


def _project(name: str) -> dict:
    return client.post("/api/project", json={"name": f"{name}-{uuid4().hex[:6]}"}).json()


@contextmanager
def _as_other_user():
    """A client authenticated as a different account. The auth dependency
    override must stay removed while requests are made, hence the context
    manager."""
    from app.core.rbac import get_current_user

    saved = app.dependency_overrides.pop(get_current_user, None)
    try:
        raw = TestClient(app, raise_server_exceptions=False)
        token = raw.post(
            "/api/auth/register",
            json={"email": f"other-{uuid4().hex[:8]}@example.com", "password": "secret-pass-123"},
        ).json()["access_token"]
        raw.headers.update({"Authorization": f"Bearer {token}"})
        yield raw
    finally:
        if saved is not None:
            app.dependency_overrides[get_current_user] = saved


def _chat_turn(ws, project_id: str, message: str, **extra):
    ws.send_json({"mode": "chat", "project_id": project_id, "message": message, "tools_enabled": False, **extra})
    while ws.receive_json().get("type") != "done":
        pass
    # Task-mode barrier: the loop iteration (incl. titling) has finished
    # once the follow-up command answers.
    ws.send_json({"mode": "task", "project_id": project_id, "message": "/help"})
    while ws.receive_json().get("type") != "task_result":
        pass


@pytest.fixture
def fake_llms(monkeypatch):
    titles: dict = {"n": 0}

    async def chat_stream(messages, **kwargs):
        yield "the answer"

    async def title_stream(messages, **kwargs):
        titles["n"] += 1
        yield '"Acme Deadline Planning."'

    monkeypatch.setattr("app.api.chat.stream_llm", chat_stream)
    monkeypatch.setattr("app.agents.session_titles.stream_llm", title_stream)
    monkeypatch.setattr(settings, "auto_titles_enabled", True)
    return titles


# ── Sessions table + titles ──────────────────────────────────────────────────

def test_session_row_created_and_titled_once(fake_llms):
    p = _project("ux-title")
    session = f"ti-{uuid4().hex[:6]}"
    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], "help me plan the Acme deadline")
        _chat_turn(ws, p["id"], "thanks, continue")

    assert fake_llms["n"] == 1, "title generated exactly once, on the first exchange"
    rows = client.get(f"/api/project/{p['id']}/sessions").json()
    assert len(rows) == 1
    entry = rows[0]
    # Cleaned: surrounding quotes and trailing period stripped.
    assert entry["title"] == "Acme Deadline Planning"
    assert entry["preview"].startswith("help me plan")
    assert entry["message_count"] == 4
    assert entry["last_at"]


def test_sidebar_falls_back_to_preview_without_title(fake_llms, monkeypatch):
    monkeypatch.setattr(settings, "auto_titles_enabled", False)
    p = _project("ux-notitle")
    with client.websocket_connect(f"/ws/chat/nt-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], "untitled conversation opener")

    rows = client.get(f"/api/project/{p['id']}/sessions").json()
    assert rows[0]["title"] == ""
    assert rows[0]["preview"].startswith("untitled conversation")
    assert fake_llms["n"] == 0


def test_rename_never_clobbered_by_auto_title():
    p = _project("ux-keep")
    session = f"kp-{uuid4().hex[:6]}"
    asyncio.run(repo.add_chat_message(p["id"], session, "user", "hello", owner_id="test-user"))
    assert asyncio.run(repo.rename_chat_session(p["id"], session, "My Name", owner_id="test-user"))
    # Auto-title path refuses to overwrite an existing title.
    assert not asyncio.run(
        repo.set_session_title_if_empty(p["id"], session, "Robot Name", owner_id="test-user")
    )
    rows = client.get(f"/api/project/{p['id']}/sessions").json()
    assert rows[0]["title"] == "My Name"


# ── Rename / delete endpoints, owner-scoped ──────────────────────────────────

def test_rename_and_delete_are_owner_scoped():
    p = _project("ux-owned")
    session = f"ow-{uuid4().hex[:6]}"
    asyncio.run(repo.add_chat_message(p["id"], session, "user", "mine", owner_id="test-user"))

    with _as_other_user() as other:
        assert other.patch(f"/api/project/{p['id']}/sessions/{session}", json={"title": "hijack"}).status_code == 404
        assert other.delete(f"/api/project/{p['id']}/sessions/{session}").status_code == 404

    res = client.patch(f"/api/project/{p['id']}/sessions/{session}", json={"title": "Renamed"})
    assert res.status_code == 200
    assert client.get(f"/api/project/{p['id']}/sessions").json()[0]["title"] == "Renamed"

    assert client.delete(f"/api/project/{p['id']}/sessions/{session}").json() == {"deleted": True}
    assert client.get(f"/api/project/{p['id']}/sessions").json() == []
    assert client.get(f"/api/project/{p['id']}/chats?session_id={session}").json() == []
    # Deleting again → 404 (row gone).
    assert client.delete(f"/api/project/{p['id']}/sessions/{session}").status_code == 404


# ── Server-side search ───────────────────────────────────────────────────────

def test_chat_search_is_owner_scoped_ilike():
    p = _project("ux-search")
    session = f"se-{uuid4().hex[:6]}"
    asyncio.run(repo.add_chat_message(p["id"], session, "user", "the Quarterly Budget numbers", owner_id="test-user"))
    asyncio.run(repo.add_chat_message(p["id"], session, "assistant", "here are the figures", owner_id="test-user"))

    hits = client.get(f"/api/project/{p['id']}/search?q=quarterly budget").json()
    assert len(hits) == 1
    assert hits[0]["session_id"] == session
    assert "Quarterly Budget" in hits[0]["snippet"]

    assert client.get(f"/api/project/{p['id']}/search?q=").json() == []
    with _as_other_user() as other:
        assert other.get(f"/api/project/{p['id']}/search?q=budget").status_code == 404


# ── Edit & resend ────────────────────────────────────────────────────────────

def test_edit_and_resend_replaces_last_exchange(fake_llms):
    p = _project("ux-edit")
    session = f"ed-{uuid4().hex[:6]}"
    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], "first question with a typoo")
        _chat_turn(ws, p["id"], "first question fixed", edit_last=True)

    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "first question fixed"
    assert not any("typoo" in m["content"] for m in history)


# ── <think> extraction ───────────────────────────────────────────────────────

def test_split_think_parser():
    from app.agents.reasoning import split_think, strip_think

    assert split_think("plain answer") == ("", "plain answer")
    assert split_think("<think>chain</think>The answer.") == ("chain", "The answer.")
    thinking, answer = split_think("<think>a</think>mid<think>b</think>end")
    assert thinking == "a\nb"
    assert answer == "midend"
    # Unclosed block (stream cut mid-thought) → all thinking, no answer.
    assert split_think("<think>never closed") == ("never closed", "")
    assert strip_think("<think>x</think>  spaced  ") == "spaced"


def test_stored_assistant_message_excludes_think(monkeypatch):
    async def reasoning_stream(messages, **kwargs):
        yield "<think>let me reason"
        yield " carefully</think>"
        yield "The capital is Paris."

    monkeypatch.setattr("app.api.chat.stream_llm", reasoning_stream)
    p = _project("ux-think")
    session = f"th-{uuid4().hex[:6]}"
    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "capital of France?", "tools_enabled": False})
        while ws.receive_json().get("type") != "done":
            pass

    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "The capital is Paris."
    assert "<think>" not in history[-1]["content"]
