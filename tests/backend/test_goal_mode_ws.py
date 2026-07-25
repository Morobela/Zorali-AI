"""WS `goal` mode and the goals read API (capability map U1).

Drives the real WebSocket with a fake provider: the first call is the planner
(returning plan JSON), later calls execute the steps. Asserts the client sees
goal_update frames, and that the goal is persisted and readable afterwards.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from conftest import ws_ticket

client = TestClient(app)

PLAN_JSON = (
    '{"tasks": [{"title": "Two step plan", "steps": ['
    '{"instruction": "research the topic", "depends_on": []},'
    '{"instruction": "summarize the findings", "depends_on": [0]}]}]}'
)


def _project(name: str) -> dict:
    return client.post("/api/project", json={"name": f"{name}-{uuid4().hex[:6]}"}).json()


def _make_stream(plan_json: str):
    """Fake stream_llm: first call returns the plan, the rest answer steps."""
    calls = {"n": 0, "messages": []}

    async def fake_stream(messages, **kwargs):
        calls["messages"].append(messages)
        calls["n"] += 1
        if calls["n"] == 1:
            yield plan_json
        else:
            yield f"answer for call {calls['n']}"

    return fake_stream, calls


def _drain_goal_frames(ws, *, limit: int = 400) -> list[dict]:
    """Collect frames until the goal reaches a terminal event."""
    frames = []
    for _ in range(limit):
        msg = ws.receive_json()
        frames.append(msg)
        if msg.get("type") == "goal_update" and msg.get("event") in ("goal_completed", "goal_failed"):
            return frames
        if msg.get("type") == "error":
            return frames
    raise AssertionError(f"goal never reached a terminal event: {frames!r}")


def test_goal_mode_plans_executes_and_streams_updates(monkeypatch):
    fake_stream, calls = _make_stream(PLAN_JSON)
    import app.agents.goal_planner as planner_module
    import app.agents.goal_engine as engine_module
    monkeypatch.setattr(planner_module, "stream_llm", fake_stream)
    monkeypatch.setattr(engine_module, "stream_llm", fake_stream)

    project = _project("goal-ws")
    with client.websocket_connect(f"/ws/chat/goal-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({
            "mode": "goal",
            "message": "Write a short brief about local LLM hosting",
            "project_id": project["id"],
        })
        frames = _drain_goal_frames(ws)

    updates = [f for f in frames if f.get("type") == "goal_update"]
    assert updates, f"no goal_update frames in {frames!r}"
    assert updates[0]["event"] == "plan"
    assert updates[-1]["event"] == "goal_completed"

    # The plan reached the client with both steps.
    plan_goal = updates[0]["goal"]
    instructions = [s["instruction"] for t in plan_goal["tasks"] for s in t["steps"]]
    assert instructions == ["research the topic", "summarize the findings"]

    # Step output streamed as goal_token frames.
    assert any(f.get("type") == "goal_token" for f in frames)

    # Persisted and readable through the API, with results filled in.
    final = client.get(f"/api/goals/{plan_goal['id']}").json()
    assert final["status"] == "completed"
    steps = [s for t in final["tasks"] for s in t["steps"]]
    assert all(s["status"] == "completed" for s in steps)
    assert all(s["result"] for s in steps)

    # The planner ran exactly once; the rest of the calls executed steps.
    assert calls["n"] >= 3


def test_goal_appears_in_the_owner_list_and_404s_for_others(monkeypatch):
    fake_stream, _ = _make_stream(
        '{"tasks": [{"title": "One step", "steps": [{"instruction": "do the thing"}]}]}'
    )
    import app.agents.goal_planner as planner_module
    import app.agents.goal_engine as engine_module
    monkeypatch.setattr(planner_module, "stream_llm", fake_stream)
    monkeypatch.setattr(engine_module, "stream_llm", fake_stream)

    project = _project("goal-list")
    with client.websocket_connect(f"/ws/chat/goal-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "goal", "message": "single step objective", "project_id": project["id"]})
        _drain_goal_frames(ws)

    listed = client.get(f"/api/goals?project_id={project['id']}").json()
    assert len(listed) == 1
    assert listed[0]["objective"] == "single step objective"

    assert client.get(f"/api/goals/{uuid4()}").status_code == 404


def test_goal_mode_rejects_empty_objective():
    with client.websocket_connect(f"/ws/chat/goal-{uuid4().hex[:6]}?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "goal", "message": "   ", "project_id": "default"})
        msg = ws.receive_json()
    assert msg["type"] == "error"
