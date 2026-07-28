"""The contract as a real client sees it, over a real socket.

`test_ws_protocol` covers the pieces in isolation. These drive
`/ws/chat/{session_id}` end to end, because the envelope is only worth
anything if it survives the whole path — including frames built inside the
goal engine and the tool loop, which never import the protocol module.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.ws_protocol import SCHEMA_VERSION
from app.main import app
from conftest import ws_ticket

client = TestClient(app)


def _session() -> str:
    return f"proto-{uuid4().hex[:8]}"


def _connect():
    return client.websocket_connect(f"/ws/chat/{_session()}?ticket={ws_ticket(client)}")


def test_a_status_frame_carries_the_envelope() -> None:
    with _connect() as ws:
        ws.send_json({"mode": "status", "request_id": "req-status"})
        frame = ws.receive_json()

    assert frame["type"] == "status"
    assert frame["schema_version"] == SCHEMA_VERSION
    assert frame["request_id"] == "req-status"
    # The payload the UI already reads is unchanged.
    assert "data" in frame


def test_an_empty_message_names_its_reason() -> None:
    with _connect() as ws:
        ws.send_json({"mode": "chat", "message": "   ", "request_id": "req-empty"})
        frame = ws.receive_json()

    assert frame["type"] == "error"
    assert frame["code"] == "empty_message"
    assert frame["content"] == "Empty message"       # unchanged for old clients
    assert frame["request_id"] == "req-empty"


def test_an_unknown_mode_is_refused_instead_of_becoming_a_chat_turn() -> None:
    # Previously `mode` was read with .get(..., "chat"), so a typo silently
    # became a chat turn — a client bug that cost a model call.
    with _connect() as ws:
        ws.send_json({"mode": "chatt", "message": "hello"})
        frame = ws.receive_json()

    assert frame["type"] == "error"
    assert frame["code"] == "unknown_mode"
    assert "chatt" in frame["content"]


def test_a_malformed_frame_gets_an_answer_rather_than_a_dropped_socket() -> None:
    with _connect() as ws:
        ws.send_json({"mode": "chat", "message": "hi", "tools_enabled": "not-a-bool"})
        frame = ws.receive_json()

        assert frame["type"] == "error"
        assert frame["code"] == "invalid_frame"

        # Still usable: the connection survived a bad frame.
        ws.send_json({"mode": "status"})
        assert ws.receive_json()["type"] == "status"


def test_the_socket_survives_an_unexpected_server_error(monkeypatch) -> None:
    """The exception-mapping wrapper, from the client's side.

    Before it, an exception mid-turn closed the socket and the user saw the
    answer stop with no explanation.
    """
    import app.api.chat as chat_module

    def boom(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(chat_module, "status_report", boom)

    with _connect() as ws:
        ws.send_json({"mode": "status", "request_id": "req-boom"})
        frame = ws.receive_json()

        assert frame["type"] == "error"
        assert frame["code"] == "internal_error"
        assert "provider exploded" in frame["content"]
        assert frame["request_id"] == "req-boom"

        # And the connection is still good afterwards.
        monkeypatch.undo()
        ws.send_json({"mode": "status"})
        assert ws.receive_json()["type"] == "status"


def test_a_task_turn_stamps_every_frame() -> None:
    project = client.post("/api/project", json={"name": f"proto-{uuid4().hex[:6]}"}).json()
    with _connect() as ws:
        ws.send_json({
            "mode": "task", "message": "/help",
            "project_id": project["id"], "request_id": "req-task",
        })
        frame = ws.receive_json()

    assert frame["type"] == "task_result"
    assert frame["schema_version"] == SCHEMA_VERSION
    assert frame["request_id"] == "req-task"
    assert frame["data"]["status"] == "complete"


def test_a_chat_turn_stamps_tokens_and_done(monkeypatch) -> None:
    import app.api.chat as chat_module

    async def fake_stream(_messages, **_kwargs):
        for chunk in ("one ", "two"):
            yield chunk

    monkeypatch.setattr(chat_module, "stream_llm", fake_stream)
    project = client.post("/api/project", json={"name": f"proto-{uuid4().hex[:6]}"}).json()

    frames = []
    with _connect() as ws:
        ws.send_json({
            "mode": "chat", "message": "hello", "project_id": project["id"],
            "tools_enabled": False, "request_id": "req-chat",
        })
        for _ in range(50):
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "done":
                break

    assert [f["type"] for f in frames][-1] == "done"
    assert any(f["type"] == "token" for f in frames)
    # Every frame of the turn, not just the first.
    assert all(f["schema_version"] == SCHEMA_VERSION for f in frames)
    assert all(f["request_id"] == "req-chat" for f in frames)


def test_frames_from_the_goal_engine_are_stamped_too(monkeypatch) -> None:
    """The goal engine builds dicts and never imports the protocol module.

    It receives the emitter in place of `websocket.send_json`, so its frames
    get the envelope without knowing about it — the property that makes this
    contract hold for producers outside `api/chat.py`.
    """
    plan = (
        '{"tasks": [{"title": "One step", "steps": ['
        '{"instruction": "do the thing", "depends_on": []}]}]}'
    )
    calls = {"n": 0}

    async def fake_stream(_messages, **_kwargs):
        calls["n"] += 1
        yield plan if calls["n"] == 1 else "step answer"

    import app.agents.goal_engine as engine_module
    import app.agents.goal_planner as planner_module
    monkeypatch.setattr(planner_module, "stream_llm", fake_stream)
    monkeypatch.setattr(engine_module, "stream_llm", fake_stream)

    project = client.post("/api/project", json={"name": f"proto-{uuid4().hex[:6]}"}).json()
    frames = []
    with _connect() as ws:
        ws.send_json({
            "mode": "goal", "message": "do a thing",
            "project_id": project["id"], "request_id": "req-goal",
        })
        for _ in range(400):
            frame = ws.receive_json()
            frames.append(frame)
            if frame.get("event") in ("goal_completed", "goal_failed") or frame["type"] == "error":
                break

    updates = [f for f in frames if f["type"] == "goal_update"]
    assert updates, f"no goal_update frames in {frames!r}"
    assert all(f["schema_version"] == SCHEMA_VERSION for f in frames)
    assert all(f["request_id"] == "req-goal" for f in frames)
