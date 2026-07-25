"""Durable goal engine (capability map U1).

The headline test is the DoD: start a three-step goal, kill the backend after
step one, restart, and the goal resumes from step two — the work does not die
with the process. "Killing the backend" is simulated the way it actually
happens: the executing coroutine stops mid-goal, leaving the plan and the
completed step in Postgres, and a fresh engine instance (as a new process
would have) resumes from persisted state.

Also covers planner parsing (the shapes local models really emit), replanning
on step failure, and the hard ceilings that guarantee termination.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agents.goal_engine import GoalEngine
from app.agents.goal_planner import normalize_plan, _extract_json_object, _normalize_steps
from app.core.config import settings
from app.db.repositories import repo

from conftest import TEST_USER_SUB

THREE_STEP_PLAN = [
    {"title": "Three step task", "steps": [
        {"instruction": "step one", "depends_on": []},
        {"instruction": "step two", "depends_on": []},
        {"instruction": "step three", "depends_on": []},
    ]},
]


@pytest.fixture(autouse=True)
def _serial_steps(monkeypatch):
    """Pin these tests to serial execution.

    They assert exact step ordering and crash-after-N semantics, which only
    have one meaning when steps run one at a time. Parallel batching (U2) is
    covered in ``test_goal_parallel_steps.py``.
    """
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 1)


def _steps_of(goal: dict) -> list[dict]:
    return [s for t in goal["tasks"] for s in t["steps"]]


def _status_map(goal: dict) -> dict[str, str]:
    return {s["instruction"]: s["status"] for s in _steps_of(goal)}


# ── planner parsing ──────────────────────────────────────────────────────────

def test_extract_json_object_handles_fences_and_preamble():
    assert _extract_json_object('```json\n{"tasks": []}\n```') == {"tasks": []}
    assert _extract_json_object('Sure! Here is the plan:\n{"tasks": []}') == {"tasks": []}
    assert _extract_json_object("not json at all") is None
    assert _extract_json_object("") is None


def test_normalize_plan_accepts_nested_shape():
    parsed = {"tasks": [{"title": "Research", "steps": [
        {"instruction": "find sources", "depends_on": []},
        {"instruction": "summarize them", "depends_on": [0]},
    ]}]}
    plan = normalize_plan(parsed, "objective")
    assert len(plan) == 1
    assert [s["instruction"] for s in plan[0]["steps"]] == ["find sources", "summarize them"]
    assert plan[0]["steps"][1]["depends_on"] == [0]


def test_normalize_plan_accepts_flat_and_string_steps():
    plan = normalize_plan({"steps": ["do a", "do b"]}, "objective")
    assert [s["instruction"] for s in plan[0]["steps"]] == ["do a", "do b"]


def test_normalize_plan_falls_back_to_single_step():
    """An unusable planner reply must still leave the goal executable."""
    for parsed in (None, {}, {"tasks": []}, {"tasks": [{"title": "", "steps": []}]}):
        plan = normalize_plan(parsed, "my objective")
        assert plan == [{"title": "my objective", "steps": [
            {"instruction": "my objective", "depends_on": []},
        ]}]


def test_normalize_steps_drops_forward_dependencies():
    """A dependency may only point at an earlier sibling step."""
    steps = _normalize_steps(
        [{"instruction": "a", "depends_on": [5]}, {"instruction": "b", "depends_on": [0, 9]}],
        limit=8,
    )
    assert steps[0]["depends_on"] == []
    assert steps[1]["depends_on"] == [0]


# ── persistence + step selection ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_next_runnable_step_respects_dependencies_and_order():
    goal = await repo.create_goal(
        "dep ordering", [
            {"title": "t", "steps": [
                {"instruction": "first", "depends_on": []},
                {"instruction": "second", "depends_on": [0]},
            ]},
        ],
        project_id="default", owner_id=TEST_USER_SUB,
    )
    gid = goal["id"]
    step = await repo.next_runnable_step(gid, owner_id=TEST_USER_SUB)
    assert step["instruction"] == "first"

    # While "first" is unfinished, the dependent step must not be handed out.
    await repo.start_step(step["id"], owner_id=TEST_USER_SUB)
    assert (await repo.next_runnable_step(gid, owner_id=TEST_USER_SUB))["instruction"] == "first"

    await repo.finish_step(step["id"], status="completed", result="r1", owner_id=TEST_USER_SUB)
    assert (await repo.next_runnable_step(gid, owner_id=TEST_USER_SUB))["instruction"] == "second"


@pytest.mark.asyncio
async def test_goals_are_owner_scoped():
    goal = await repo.create_goal(
        "private objective", THREE_STEP_PLAN, project_id="default", owner_id=TEST_USER_SUB
    )
    assert await repo.get_goal(goal["id"], owner_id="someone-else") is None
    assert await repo.next_runnable_step(goal["id"], owner_id="someone-else") is None


# ── the U1 definition of done ────────────────────────────────────────────────

class _ScriptedEngine(GoalEngine):
    """Engine whose step execution is scripted instead of calling a provider.

    ``crash_after`` raises RuntimeError once that many steps have run, which
    is how this test simulates the backend being killed mid-goal.
    """

    def __init__(self, *, crash_after: int | None = None, fail_instructions: set[str] | None = None):
        super().__init__()
        self.executed: list[str] = []
        # (goal_id, instruction) pairs — the resume sweep is global, so tests
        # that call it filter execution down to their own goal.
        self.executed_by_goal: list[tuple[str, str]] = []
        self._crash_after = crash_after
        self._fail = fail_instructions or set()

    def executed_for(self, goal_id: str) -> list[str]:
        return [instruction for gid, instruction in self.executed_by_goal if gid == goal_id]

    async def _run_step(self, step, **kwargs):  # type: ignore[override]
        if self._crash_after is not None and len(self.executed) >= self._crash_after:
            raise RuntimeError("simulated backend kill")
        self.executed.append(step["instruction"])
        self.executed_by_goal.append((step["goal_id"], step["instruction"]))
        if step["instruction"] in self._fail:
            return "", "tool exploded"
        return f"result of {step['instruction']}", None


@pytest.mark.asyncio
async def test_goal_resumes_from_step_two_after_a_simulated_restart():
    """U1 DoD: three-step goal, backend killed after step one, restart,
    resume continues from step two and never re-runs step one."""
    goal = await repo.create_goal(
        "three step objective", THREE_STEP_PLAN,
        project_id="default", session_id="dod", owner_id=TEST_USER_SUB, status="running",
    )
    gid = goal["id"]

    # ── process 1: dies right after step one completes ──
    dying = _ScriptedEngine(crash_after=1)
    with pytest.raises(RuntimeError):
        await dying.execute_goal(gid, owner_id=TEST_USER_SUB)
    assert dying.executed == ["step one"]

    persisted = await repo.get_goal(gid, owner_id=TEST_USER_SUB)
    statuses = _status_map(persisted)
    assert statuses["step one"] == "completed", "step one's result must be durable"
    assert persisted["status"] == "running", "an interrupted goal stays running for the resume sweep"
    assert _steps_of(persisted)[0]["result"] == "result of step one"

    # ── process 2: a fresh engine, as a restarted backend would have ──
    revived = _ScriptedEngine()
    resumed_ids = await revived.resume_unfinished_goals()
    assert gid in resumed_ids

    # The resumed process ran ONLY the remaining steps of this goal — step one
    # is never re-executed, which is the whole point of the DoD.
    assert revived.executed_for(gid) == ["step two", "step three"]

    final = await repo.get_goal(gid, owner_id=TEST_USER_SUB)
    assert final["status"] == "completed"
    assert _status_map(final) == {
        "step one": "completed", "step two": "completed", "step three": "completed",
    }
    # Step one's original result survived the restart untouched.
    assert _steps_of(final)[0]["result"] == "result of step one"
    assert final["tasks"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_resume_reruns_a_step_that_was_mid_flight():
    """A step still ``running`` when the process died has no result, so the
    resume must run it again (not skip it as done)."""
    goal = await repo.create_goal(
        "interrupted mid-step", [{"title": "t", "steps": [
            {"instruction": "only step", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )
    step = await repo.next_runnable_step(goal["id"], owner_id=TEST_USER_SUB)
    await repo.start_step(step["id"], owner_id=TEST_USER_SUB)  # left running by the "kill"

    revived = _ScriptedEngine()
    await revived.resume_unfinished_goals()
    assert revived.executed_for(goal["id"]) == ["only step"]
    final = await repo.get_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "completed"


# ── replanning ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_step_triggers_replan_and_the_goal_continues(monkeypatch):
    """A failing step is recorded, the planner rewrites the remaining work,
    and execution continues with the new steps."""
    import app.agents.goal_engine as engine_module

    replan_calls: list[dict] = []

    async def fake_replan(objective, *, failed_instruction, error, completed, remaining, **kwargs):
        replan_calls.append({
            "failed": failed_instruction, "error": error,
            "completed": [c["instruction"] for c in completed],
        })
        return [{"instruction": "recovered step", "depends_on": []}]

    monkeypatch.setattr(engine_module, "replan", fake_replan)

    goal = await repo.create_goal(
        "replan objective", [{"title": "t", "steps": [
            {"instruction": "good step", "depends_on": []},
            {"instruction": "bad step", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )
    engine = _ScriptedEngine(fail_instructions={"bad step"})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert engine.executed == ["good step", "bad step", "recovered step"]
    assert final["status"] == "completed"
    # The planner saw the failure context and what had already succeeded.
    assert replan_calls[0]["failed"] == "bad step"
    assert replan_calls[0]["error"] == "tool exploded"
    assert replan_calls[0]["completed"] == ["good step"]
    # The failed step is preserved as the durable record of what went wrong.
    statuses = _status_map(final)
    assert statuses["bad step"] == "failed"
    assert statuses["recovered step"] == "completed"


@pytest.mark.asyncio
async def test_goal_fails_when_replan_declines(monkeypatch):
    import app.agents.goal_engine as engine_module

    async def no_replan(*args, **kwargs):
        return []

    monkeypatch.setattr(engine_module, "replan", no_replan)

    goal = await repo.create_goal(
        "hopeless objective", [{"title": "t", "steps": [
            {"instruction": "bad step", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )
    engine = _ScriptedEngine(fail_instructions={"bad step"})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "failed"
    assert "no viable replan" in final["error"]


@pytest.mark.asyncio
async def test_replan_budget_stops_a_runaway_loop(monkeypatch):
    """A planner that always proposes another doomed step still terminates."""
    import app.agents.goal_engine as engine_module

    async def always_replan(*args, **kwargs):
        return [{"instruction": "bad step", "depends_on": []}]

    monkeypatch.setattr(engine_module, "replan", always_replan)
    monkeypatch.setattr(settings, "goal_max_replans", 2)

    goal = await repo.create_goal(
        "loop objective", [{"title": "t", "steps": [
            {"instruction": "bad step", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )
    engine = _ScriptedEngine(fail_instructions={"bad step"})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "failed"
    assert "replan budget exhausted" in final["error"]
    # Original attempt + one per replan, then it stops.
    assert len(engine.executed) == 3


# ── events ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_emits_goal_update_events_with_the_full_checklist():
    goal = await repo.create_goal(
        "event objective", [{"title": "t", "steps": [
            {"instruction": "step one", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )
    events: list[dict] = []

    async def emit(payload):
        events.append(payload)

    engine = _ScriptedEngine()
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB, emit=emit)

    kinds = [e["event"] for e in events if e.get("type") == "goal_update"]
    assert kinds == ["step_started", "step_completed", "goal_completed"]
    # Every frame carries the whole goal, so a dropped frame cannot desync the UI.
    for event in events:
        assert event["goal"]["id"] == goal["id"]
        assert event["goal"]["tasks"][0]["steps"]


@pytest.mark.asyncio
async def test_emit_failure_does_not_abort_the_goal():
    """A closed socket must not kill a goal that is otherwise progressing."""
    goal = await repo.create_goal(
        "emit failure", [{"title": "t", "steps": [
            {"instruction": "step one", "depends_on": []},
        ]}],
        project_id="default", owner_id=TEST_USER_SUB, status="running",
    )

    async def broken_emit(_payload):
        raise RuntimeError("socket closed")

    engine = _ScriptedEngine()
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB, emit=broken_emit)
    assert final["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_goals_do_not_interfere():
    """Two goals running at once keep their own step state."""
    plans = [
        [{"title": "a", "steps": [{"instruction": f"a{i}", "depends_on": []} for i in range(2)]}],
        [{"title": "b", "steps": [{"instruction": f"b{i}", "depends_on": []} for i in range(2)]}],
    ]
    goals = [
        await repo.create_goal(f"objective {n}", plan, project_id="default",
                               owner_id=TEST_USER_SUB, status="running")
        for n, plan in enumerate(plans)
    ]
    engines = [_ScriptedEngine(), _ScriptedEngine()]
    finals = await asyncio.gather(*(
        engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
        for engine, goal in zip(engines, goals)
    ))
    assert engines[0].executed == ["a0", "a1"]
    assert engines[1].executed == ["b0", "b1"]
    assert [f["status"] for f in finals] == ["completed", "completed"]
