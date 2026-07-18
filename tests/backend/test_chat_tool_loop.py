"""Model-driven tool use in the default chat path (Phase 1).

Covers the WS path with a fake provider that emits a TOOL_CALL and then a
final answer:

  1. Tool executed with the ticket user's caller context; tool_use /
     tool_result events emitted in order around the answer tokens.
  2. Hard cap of 5 tool calls per turn is enforced and the turn still ends
     with a done frame.
  3. A non-admin caller invoking code_execution gets a clean tool error fed
     back to the loop — no crash, and the turn completes.
  4. A plain answer with no TOOL_CALL behaves exactly as before (token frames,
     no tool events, message persisted).
  5. tools_enabled=false keeps the always-on retrieval (with settings.rag_top_k)
     while tools-on turns skip it.
  6. document_search results reach the model inside an UNTRUSTED block and
     produce citations in the done frame.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.registry import ToolSpec, registry
from conftest import ws_ticket

client = TestClient(app)


def _project(name: str) -> dict:
    return client.post("/api/project", json={"name": f"{name}-{uuid4().hex[:6]}"}).json()


def _drain_until_done(ws) -> list[dict]:
    frames = []
    for _ in range(400):
        msg = ws.receive_json()
        frames.append(msg)
        if msg.get("type") == "done":
            return frames
    raise AssertionError("no done frame received")


def _make_stream(responses: list[list[str]]):
    """Fake stream_llm: the n-th call streams the n-th response's chunks
    (the last response repeats for any further calls). Records the messages
    passed to each call."""
    calls: dict = {"n": 0, "messages": []}

    async def fake_stream(messages, **kwargs):
        calls["messages"].append(messages)
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        for chunk in responses[index]:
            yield chunk

    return fake_stream, calls


@pytest.fixture
def probe_tool():
    """Ephemeral registry tool that records the caller context it ran with."""
    name = f"_probe_{uuid4().hex[:6]}"
    record: list[dict] = []

    async def handler(inputs, caller):
        record.append({"inputs": inputs, "caller": caller})
        return {"echo": inputs.get("q", "")}

    registry.register(ToolSpec(
        name=name,
        input_schema={"q": "string"},
        output_schema={"echo": "string"},
        handler=lambda x, c: handler(x, c),
        requires_role="user",
        needs_caller=True,
    ))
    yield name, record
    registry._tools.pop(name, None)


# ── 1. Tool call then answer: caller, event order ─────────────────────────────

def test_tool_call_executes_with_ticket_caller_and_events_in_order(monkeypatch, probe_tool):
    name, record = probe_tool
    fake_stream, _calls = _make_stream([
        ["Let me check.\n", "TOOL_", f'CALL: {{"tool": "{name}", "inputs": {{"q": "ping"}}}}'],
        ["The probe ", "answered pong."],
    ])
    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("toolloop")
    session = f"tl-{uuid4().hex[:6]}"

    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "use the probe"})
        frames = _drain_until_done(ws)

    # The tool ran on behalf of the authenticated ticket user.
    assert record == [{"inputs": {"q": "ping"}, "caller": "test-user"}]

    kinds = [f["type"] for f in frames]
    use_at = kinds.index("tool_use")
    result_at = kinds.index("tool_result")
    assert use_at < result_at
    assert frames[use_at]["tool"] == name
    assert frames[use_at]["inputs"] == {"q": "ping"}
    assert frames[result_at]["ok"] is True

    # The preamble streams before the tool step, the answer after it, and the
    # TOOL_CALL text never reaches the client or the stored message.
    token_indexes = [i for i, f in enumerate(frames) if f["type"] == "token"]
    assert token_indexes[-1] > result_at, "answer tokens stream after the tool step"
    visible = "".join(f["content"] for f in frames if f["type"] == "token")
    assert visible == "Let me check.\nThe probe answered pong."

    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    assert history[-1]["role"] == "assistant"
    assert "TOOL_CALL" not in history[-1]["content"]
    assert history[-1]["content"].endswith("The probe answered pong.")


# ── 2. Hard cap of 5 tool calls per turn ──────────────────────────────────────

def test_tool_call_cap_of_five_enforced(monkeypatch, probe_tool):
    name, record = probe_tool
    # The model asks for a tool on every segment, forever.
    fake_stream, _calls = _make_stream([
        [f'TOOL_CALL: {{"tool": "{name}", "inputs": {{"q": "again"}}}}'],
    ])
    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("toolcap")

    with client.websocket_connect(f"/ws/chat/cap-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "loop forever"})
        frames = _drain_until_done(ws)

    assert len(record) == 5, "exactly 5 tool executions despite endless TOOL_CALLs"
    assert sum(1 for f in frames if f["type"] == "tool_use") == 5
    assert frames[-1]["type"] == "done"


# ── 3. Role denial: non-admin code_execution is a clean tool error ────────────

@pytest.mark.asyncio
async def test_non_admin_code_execution_gets_clean_error():
    from app.agents.chat_tools import run_chat_tool_loop

    fake_stream, calls = _make_stream([
        ['TOOL_CALL: {"tool": "code_execution", "inputs": {"code": "print(1)"}}'],
        ["I am not allowed to run code."],
    ])
    tokens: list[str] = []
    events: list[dict] = []

    async def emit_token(text):
        tokens.append(text)

    async def emit_event(payload):
        events.append(payload)

    result = await run_chat_tool_loop(
        [{"role": "user", "content": "run some code"}],
        stream=lambda msgs: fake_stream(msgs),
        emit_token=emit_token,
        emit_event=emit_event,
        caller="test-user",
        caller_role="user",  # not admin
        project_id="default",
    )

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["ok"] is False
    assert "requires role 'admin'" in tool_result["summary"]
    assert "".join(tokens) == "I am not allowed to run code."
    assert result["tool_calls"] == 1
    # The denial was fed back to the model as a message, not raised.
    followup = calls["messages"][1]
    assert any("requires role 'admin'" in m["content"] for m in followup if m["role"] == "system")


# ── 4. Plain answer parity ────────────────────────────────────────────────────

def test_plain_answer_without_tool_call_behaves_as_before(monkeypatch):
    fake_stream, calls = _make_stream([["Hello ", "there."]])
    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("plain")
    session = f"plain-{uuid4().hex[:6]}"

    with client.websocket_connect(f"/ws/chat/{session}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "hi"})
        frames = _drain_until_done(ws)

    kinds = [f["type"] for f in frames]
    assert "tool_use" not in kinds and "tool_result" not in kinds
    assert "".join(f["content"] for f in frames if f["type"] == "token") == "Hello there."
    assert frames[-1]["type"] == "done"
    assert frames[-1]["citations"] == []
    assert calls["n"] == 1  # a single provider call, exactly as before

    history = client.get(f"/api/project/{p['id']}/chats?session_id={session}").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[-1]["content"] == "Hello there."


# ── 5. Retrieval routing: always-on only when tools are off ───────────────────

def test_retrieval_skipped_when_tools_on_and_kept_when_off(monkeypatch):
    from app.core.config import settings
    from app.memory.retrieval import hybrid_retriever

    retrieve_calls: list[dict] = []
    original = hybrid_retriever.retrieve

    async def spy_retrieve(query, top_k=5, *, project_id, owner_id):
        retrieve_calls.append({"top_k": top_k})
        return await original(query, top_k, project_id=project_id, owner_id=owner_id)

    monkeypatch.setattr(hybrid_retriever, "retrieve", spy_retrieve)
    fake_stream, _ = _make_stream([["ok"]])
    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("routing")

    with client.websocket_connect(f"/ws/chat/rt-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        # Default payload → tools on → no unconditional retrieval.
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "question one"})
        _drain_until_done(ws)
        assert retrieve_calls == []

        # tools_enabled=false → the pre-Phase-1 always-on retrieval, using
        # the configurable RAG_TOP_K.
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "question two", "tools_enabled": False})
        _drain_until_done(ws)
        assert [c["top_k"] for c in retrieve_calls] == [settings.rag_top_k]


# ── 6. document_search: UNTRUSTED framing + citations in the done frame ──────

def test_document_search_untrusted_framing_and_citations(monkeypatch):
    fake_stream, calls = _make_stream([
        ['TOOL_CALL: {"tool": "document_search", "inputs": {"query": "capital of France"}}'],
        ["Paris is the capital."],
    ])
    monkeypatch.setattr("app.api.chat.stream_llm", fake_stream)
    p = _project("docsearch")
    files = {"file": ("facts.txt", b"Paris is the capital of France", "text/plain")}
    client.post(f"/api/files/upload?project_id={p['id']}", files=files)

    with client.websocket_connect(f"/ws/chat/ds-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "chat", "project_id": p["id"], "message": "capital of France?"})
        frames = _drain_until_done(ws)

    done = frames[-1]
    assert done["citations"], "document_search hits should surface as citations"
    assert {"file_id", "filename", "chunk_id", "score"}.issubset(done["citations"][0].keys())

    # The result reached the model wrapped in the UNTRUSTED evidence framing
    # (project_id was auto-filled from the chat's project).
    followup = calls["messages"][1]
    tool_msgs = [m["content"] for m in followup if m["role"] == "system"]
    assert any(
        "Result of document_search (UNTRUSTED external content" in m and "Paris is the capital of France" in m
        for m in tool_msgs
    )

    # The tools system prompt itself is present on tools-on turns.
    first_call = calls["messages"][0]
    assert any("TOOL_CALL" in m["content"] for m in first_call if m["role"] == "system")
