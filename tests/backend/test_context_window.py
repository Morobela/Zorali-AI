"""Context-window management (Phase 2).

- Short histories are untouched: no summarizer call, no summary message.
- A history over the CONTEXT_MAX_TOKENS budget triggers exactly one
  summarization LLM call; the rolling summary is persisted and reused on the
  next turn instead of being recomputed.
- The summary rides into the prompt as one system message
  ("Conversation summary so far: …") while the last CONTEXT_KEEP_MESSAGES
  stay verbatim.
- session_summaries rows are owner-scoped.
"""
from __future__ import annotations

import asyncio
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


def _drain_until_done(ws):
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "done":
            return


def _seed_history(project_id: str, session_id: str, turns: int, chars_per_msg: int = 400):
    async def _seed():
        for i in range(turns):
            await repo.add_chat_message(
                project_id, session_id, "user", f"question {i} " + ("q" * chars_per_msg), owner_id="test-user"
            )
            await repo.add_chat_message(
                project_id, session_id, "assistant", f"answer {i} " + ("a" * chars_per_msg), owner_id="test-user"
            )
    asyncio.run(_seed())


@pytest.fixture
def patched_llms(monkeypatch):
    """Separate fakes for the chat stream and the summarizer's LLM call."""
    chat_calls: dict = {"messages": []}
    summary_calls: dict = {"n": 0}

    async def fake_chat_stream(messages, **kwargs):
        chat_calls["messages"].append(messages)
        yield "ok"

    async def fake_summary_stream(messages, **kwargs):
        summary_calls["n"] += 1
        yield "user asked many questions; assistant answered them"

    monkeypatch.setattr("app.api.chat.stream_llm", fake_chat_stream)
    monkeypatch.setattr("app.memory.compression.stream_llm", fake_summary_stream)
    return chat_calls, summary_calls


# ── Unit: estimator and splitter ─────────────────────────────────────────────

def test_estimate_tokens_chars_over_four():
    from app.memory.context_pruner import estimate_tokens

    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1          # minimum 1 for non-empty
    assert estimate_tokens("a" * 400) == 100    # chars/4


def test_split_history_within_budget_is_untouched():
    from app.memory.context_pruner import split_history_for_budget

    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    older, recent = split_history_for_budget(history, max_tokens=100, keep_messages=8)
    assert older == []
    assert recent == history


def test_split_history_over_budget_keeps_trailing_window():
    from app.memory.context_pruner import split_history_for_budget

    history = [{"role": "user", "content": "x" * 100} for _ in range(20)]
    older, recent = split_history_for_budget(history, max_tokens=50, keep_messages=8)
    assert len(recent) == 8
    assert older == history[:12]
    assert older + recent == history


# ── Integration: summarize once, reuse next turn ─────────────────────────────

def test_long_history_summarized_once_and_reused(monkeypatch, patched_llms):
    chat_calls, summary_calls = patched_llms
    # 10 seeded turns × ~128 tokens/message ≈ 2560 tokens — over the shrunk
    # 2000-token budget, while the ~256 tokens a new turn adds stay under the
    # refresh threshold (budget/4 = 500) so the summary is reused next turn.
    monkeypatch.setattr(settings, "context_max_tokens", 2000)
    p = _project("ctx-long")
    session = f"ctx-{uuid4().hex[:6]}"
    _seed_history(p["id"], session, turns=10, chars_per_msg=500)

    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "and now?", "tools_enabled": False})
        _drain_until_done(ws)

    assert summary_calls["n"] == 1, "long history triggers summarization exactly once"

    prompt = chat_calls["messages"][0]
    summary_msgs = [m for m in prompt if m["role"] == "system" and m["content"].startswith("Conversation summary so far:")]
    assert len(summary_msgs) == 1
    assert "assistant answered them" in summary_msgs[0]["content"]
    # Only the trailing window (plus the new user turn) stays verbatim.
    non_system = [m for m in prompt if m["role"] != "system"]
    assert len(non_system) == settings.context_keep_messages
    assert non_system[-1]["content"] == "and now?"
    assert not any("question 0" in m["content"] for m in non_system)

    # The rolling summary is persisted, owner-scoped.
    stored = asyncio.run(repo.get_session_summary(p["id"], session, owner_id="test-user"))
    assert stored is not None
    assert stored["summary"] == "user asked many questions; assistant answered them"
    assert stored["covered_messages"] > 0

    # Next turn: the stored summary is reused — no second summarizer call.
    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "follow-up", "tools_enabled": False})
        _drain_until_done(ws)

    assert summary_calls["n"] == 1, "summary reused on the next turn, not recomputed"
    prompt2 = chat_calls["messages"][1]
    assert any(
        m["role"] == "system" and m["content"].startswith("Conversation summary so far:") for m in prompt2
    )


def test_short_history_untouched(patched_llms):
    chat_calls, summary_calls = patched_llms
    p = _project("ctx-short")
    session = f"short-{uuid4().hex[:6]}"

    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "hello", "tools_enabled": False})
        _drain_until_done(ws)

    assert summary_calls["n"] == 0
    prompt = chat_calls["messages"][0]
    assert not any("Conversation summary so far:" in m["content"] for m in prompt)
    assert asyncio.run(repo.get_session_summary(p["id"], session, owner_id="test-user")) is None


# ── Ownership ─────────────────────────────────────────────────────────────────

def test_session_summary_rows_are_owner_scoped():
    p = _project("ctx-owned")
    session = f"own-{uuid4().hex[:6]}"
    asyncio.run(repo.upsert_session_summary(p["id"], session, "their plans", 4, owner_id="test-user"))

    mine = asyncio.run(repo.get_session_summary(p["id"], session, owner_id="test-user"))
    assert mine is not None and mine["summary"] == "their plans"
    # Another account sees nothing — same 404-shaped behaviour as chats.
    other = asyncio.run(repo.get_session_summary(p["id"], session, owner_id="someone-else"))
    assert other is None
