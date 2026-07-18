"""Automatic memory extraction with review (Phase 3).

- A chat turn containing "I work at Acme and my deadline is Friday" produces
  a pending candidate (pattern extractor path).
- Pending candidates are invisible everywhere that matters: memory search,
  semantic search and graph context.
- Accepting promotes to a normal memory: searchable and graph triples stored.
- Rejecting deletes the candidate outright.
- Near-identical candidates are deduplicated; AUTO_MEMORY_ENABLED=false
  disables the whole pipeline; the LLM fallback catches phrasings the
  patterns miss.

Determinism: the extractor runs inside the WS loop iteration right after the
done frame, so a follow-up task-mode round trip ("/help" → task_result) is a
barrier guaranteeing extraction finished before assertions run.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from conftest import ws_ticket

client = TestClient(app)

ACME_MSG = "I work at Acme and my deadline is Friday"


def _project(name: str) -> dict:
    return client.post("/api/project", json={"name": f"{name}-{uuid4().hex[:6]}"}).json()


def _chat_turn(ws, project_id: str, message: str):
    """One chat turn plus a task-mode barrier so extraction has finished."""
    ws.send_json({"mode": "chat", "project_id": project_id, "message": message, "tools_enabled": False})
    while ws.receive_json().get("type") != "done":
        pass
    ws.send_json({"mode": "task", "project_id": project_id, "message": "/help"})
    while ws.receive_json().get("type") != "task_result":
        pass


@pytest.fixture
def fake_llms(monkeypatch):
    """Fake chat stream; LLM-fallback extractor answers NONE unless changed."""
    fallback: dict = {"reply": "NONE", "n": 0}

    async def chat_stream(messages, **kwargs):
        yield "ok"

    async def fallback_stream(messages, **kwargs):
        fallback["n"] += 1
        yield fallback["reply"]

    monkeypatch.setattr("app.api.chat.stream_llm", chat_stream)
    monkeypatch.setattr("app.memory.auto_extract.stream_llm", fallback_stream)
    # The suite-wide conftest default is off (see conftest.py) — enable it
    # here with the LLM calls safely faked.
    monkeypatch.setattr(settings, "auto_memory_enabled", True)
    return fallback


def test_chat_turn_produces_pending_candidate_invisible_until_accepted(fake_llms):
    p = _project("automem")
    with client.websocket_connect(f"/ws/chat/am-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], ACME_MSG)

    pending = client.get(f"/api/memory/pending?project_id={p['id']}").json()
    assert len(pending) == 1
    assert "Acme" in pending[0]["text"]
    assert pending[0]["status"] == "pending"
    assert fake_llms["n"] == 0, "pattern hit — LLM fallback not consulted"

    # Pending is invisible to search, semantic search and graph context.
    assert client.get(f"/api/memory/search?project_id={p['id']}&q=Acme").json() == []
    semantic = client.get(f"/api/memory/semantic-search?project_id={p['id']}&q=Acme").json()
    assert semantic["results"] == []
    graph = client.get(f"/api/memory/graph?project_id={p['id']}&q=where do I work").json()
    assert graph["triples"] == []


def test_accept_makes_memory_searchable_and_graphed(fake_llms):
    p = _project("automem-accept")
    with client.websocket_connect(f"/ws/chat/ac-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], ACME_MSG)

    pending = client.get(f"/api/memory/pending?project_id={p['id']}").json()
    res = client.post(f"/api/memory/{pending[0]['id']}/accept").json()
    assert res["accepted"] is True
    assert any(t["relation"] == "works_at" for t in res["triples"])

    hits = client.get(f"/api/memory/search?project_id={p['id']}&q=Acme").json()
    assert hits and "Acme" in hits[0]["text"]
    graph = client.get(f"/api/memory/graph?project_id={p['id']}&q=where do I work").json()
    assert any(t["relation"] == "works_at" for t in graph["triples"])
    assert client.get(f"/api/memory/pending?project_id={p['id']}").json() == []


def test_reject_deletes_candidate_for_good(fake_llms):
    p = _project("automem-reject")
    with client.websocket_connect(f"/ws/chat/rj-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], "I live in Berlin")

    pending = client.get(f"/api/memory/pending?project_id={p['id']}").json()
    assert len(pending) == 1
    res = client.post(f"/api/memory/{pending[0]['id']}/reject").json()
    assert res["rejected"] is True

    assert client.get(f"/api/memory/pending?project_id={p['id']}").json() == []
    assert client.get(f"/api/memory/search?project_id={p['id']}&q=Berlin").json() == []
    graph = client.get(f"/api/memory/graph?project_id={p['id']}&q=where do I live").json()
    assert graph["triples"] == []


def test_near_identical_candidates_are_deduplicated(fake_llms):
    p = _project("automem-dedupe")
    with client.websocket_connect(f"/ws/chat/dd-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], ACME_MSG)
        # Same fact again (case/punctuation jitter) — no second candidate.
        _chat_turn(ws, p["id"], "I work at Acme, and my deadline is Friday!")

    pending = client.get(f"/api/memory/pending?project_id={p['id']}").json()
    assert len(pending) == 1


def test_auto_memory_can_be_disabled(monkeypatch, fake_llms):
    monkeypatch.setattr(settings, "auto_memory_enabled", False)
    p = _project("automem-off")
    with client.websocket_connect(f"/ws/chat/off-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], ACME_MSG)

    assert client.get(f"/api/memory/pending?project_id={p['id']}").json() == []


def test_llm_fallback_covers_pattern_misses(fake_llms):
    fake_llms["reply"] = "The quarterly report must use the new template"
    p = _project("automem-fallback")
    with client.websocket_connect(f"/ws/chat/fb-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        _chat_turn(ws, p["id"], "please remember the quarterly report must follow the new template")

    assert fake_llms["n"] == 1
    pending = client.get(f"/api/memory/pending?project_id={p['id']}").json()
    assert len(pending) == 1
    assert pending[0]["text"] == "The quarterly report must use the new template"


def test_duplicate_detector_units():
    from app.memory.auto_extract import _is_duplicate

    assert _is_duplicate("I work at Acme", ["i work at acme."])
    assert _is_duplicate("I work at Acme!", ["I work at Acme"])
    assert not _is_duplicate("I work at Acme", ["I live in Berlin"])
    assert _is_duplicate("", ["anything"])  # empty text is never a candidate
