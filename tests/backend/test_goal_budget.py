"""Per-goal cost budgets (capability map U7).

The DoD: a goal with a deliberately low cap pauses itself and says why.

Cost is attributed with a context-scoped meter rather than a global counter,
so these tests also pin down the property that makes it trustworthy — two
steps running concurrently must not contaminate each other's total.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agents.goal_engine import GoalEngine
from app.core.config import settings
from app.db.repositories import repo
from app.inference.cost_meter import UNCAPPED, CostMeter, cost_meter, current_meter, record_cost
from app.main import app
from app.orchestration.task_queue import ExecutionMode, QueuedTask, TaskQueue

from conftest import TEST_USER_SUB

client = TestClient(app)

TWO_STEPS = [{"title": "spending task", "steps": [
    {"instruction": "step one", "depends_on": []},
    {"instruction": "step two", "depends_on": [0]},
]}]


class _PricedEngine(GoalEngine):
    """Engine whose every step costs a fixed amount of (pretend) money."""

    def __init__(self, price_per_step: float = 0.10):
        super().__init__()
        self.price = price_per_step
        self.executed: list[str] = []

    async def _run_step(self, step, **kwargs):  # type: ignore[override]
        self.executed.append(step["instruction"])
        # Exactly how a provider call reports its cost.
        record_cost(self.price, "openai")
        return f"result of {step['instruction']}", None


async def _goal(plan=None, *, cap: float, objective="budgeted objective", model="", local_first=True):
    return await repo.create_goal(
        objective, plan or TWO_STEPS, project_id="default",
        owner_id=TEST_USER_SUB, status="running", max_cost_usd=cap,
        model=model, local_first=local_first,
    )


# ── the meter ────────────────────────────────────────────────────────────────

def test_record_cost_outside_a_meter_is_a_noop():
    record_cost(1.23, "openai")  # must not raise
    assert current_meter() is None


def test_meter_totals_calls_and_providers():
    with cost_meter() as meter:
        record_cost(0.01, "openai")
        record_cost(0.02, "openai")
        record_cost(0.0, "ollama")
    assert meter.total_usd == pytest.approx(0.03)
    assert meter.calls == 3
    assert meter.by_provider == {"openai": pytest.approx(0.03), "ollama": 0.0}


def test_nested_meters_both_see_the_spend():
    """An inner scope must not shadow the outer one — the task queue meters a
    whole task while the engine meters each step inside it."""
    with cost_meter() as outer:
        record_cost(0.01, "openai")
        with cost_meter() as inner:
            record_cost(0.02, "openai")
        assert inner.total_usd == pytest.approx(0.02)
    assert outer.total_usd == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_concurrent_meters_do_not_contaminate_each_other():
    """Parallel steps (U2) run in their own tasks; each must bill only itself."""
    async def priced(amount: float) -> float:
        with cost_meter() as meter:
            await asyncio.sleep(0.01)
            record_cost(amount, "openai")
            await asyncio.sleep(0.01)
            return meter.total_usd

    totals = await asyncio.gather(priced(0.01), priced(0.05), priced(0.25))
    assert totals == [pytest.approx(0.01), pytest.approx(0.05), pytest.approx(0.25)]


def test_provider_router_reports_cost_into_the_meter(monkeypatch):
    """The router is what actually pays; it must feed the meter."""
    import app.providers.provider_router as pr_module

    class _FakeProvider:
        name = "openai"

        async def stream_chat(self, messages, model=None):
            yield "hello"

    monkeypatch.setattr(pr_module.router, "cloud", _FakeProvider())
    monkeypatch.setattr(pr_module.router, "ollama", _FakeProvider())
    monkeypatch.setattr(
        pr_module.energy_scorer, "should_prefer_local", lambda *a, **k: False
    )

    async def drain():
        with cost_meter() as meter:
            async for _ in pr_module.router.stream_chat(
                [{"role": "user", "content": "hi"}], model="gpt-4o"
            ):
                pass
            return meter

    meter = asyncio.run(drain())
    assert meter.calls == 1
    assert meter.total_usd > 0, "a priced cloud model must register a cost"


# ── accumulation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step_and_goal_costs_accumulate():
    goal = await _goal(cap=0)  # uncapped: runs to completion
    engine = _PricedEngine(price_per_step=0.02)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    assert final["cost_usd"] == pytest.approx(0.04)
    steps = [s for t in final["tasks"] for s in t["steps"]]
    assert all(s["cost_usd"] == pytest.approx(0.02) for s in steps)


@pytest.mark.asyncio
async def test_uncapped_goals_never_pause():
    goal = await _goal(cap=0)
    engine = _PricedEngine(price_per_step=5.0)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "completed"
    assert final["cost_usd"] == pytest.approx(10.0)


# ── the U7 definition of done ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_goal_with_a_low_cap_pauses_itself_and_says_why():
    """U7 DoD: a deliberately low cap makes the goal pause itself, explain the
    numbers, notify the owner, and leave the remaining work untouched."""
    goal = await _goal(cap=0.10)  # one step's spend crosses 80% of this
    engine = _PricedEngine(price_per_step=0.09)

    before = {n["id"] for n in await repo.list_notifications(owner_id=TEST_USER_SUB)}
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    # It stopped itself after the first step.
    assert final["status"] == "paused"
    assert engine.executed == ["step one"], "the second step must not have run"

    # And it says why, in numbers a human can act on.
    reason = final["pause_reason"]
    assert "0.09" in reason and "0.10" in reason
    assert "80%" in reason
    assert "raise the cap" in reason.lower()

    # The unrun step is still pending, not lost.
    steps = {s["instruction"]: s["status"] for t in final["tasks"] for s in t["steps"]}
    assert steps == {"step one": "completed", "step two": "pending"}

    # The owner was told without asking.
    after = await repo.list_notifications(owner_id=TEST_USER_SUB)
    fresh = [n for n in after if n["id"] not in before and n["kind"] == "goal_paused"]
    assert fresh, "a paused goal must notify its owner"
    assert "budget" in fresh[0]["title"].lower()
    assert fresh[0]["read"] is False


@pytest.mark.asyncio
async def test_paused_goal_is_not_auto_resumed_by_the_boot_sweep():
    """A pause is a decision point: only a human restarts it."""
    goal = await _goal(cap=0.10)
    engine = _PricedEngine(price_per_step=0.09)
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    unfinished = [g["id"] for g in await repo.list_unfinished_goals()]
    assert goal["id"] not in unfinished

    reviver = _PricedEngine()
    await reviver.resume_unfinished_goals()
    assert reviver.executed == []


@pytest.mark.asyncio
async def test_resume_after_raising_the_cap_finishes_the_goal():
    goal = await _goal(cap=0.10)
    engine = _PricedEngine(price_per_step=0.09)
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert (await repo.get_goal(goal["id"], owner_id=TEST_USER_SUB))["status"] == "paused"

    await repo.set_goal_budget(goal["id"], 10.0, owner_id=TEST_USER_SUB)
    await repo.set_goal_status(goal["id"], "running", owner_id=TEST_USER_SUB)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    assert engine.executed == ["step one", "step two"]
    assert final["cost_usd"] == pytest.approx(0.18)
    # Resuming clears the stale explanation.
    assert final["pause_reason"] == ""


@pytest.mark.asyncio
async def test_resuming_without_more_budget_pauses_again():
    """Honest behaviour: the goal restarts, re-checks, and parks again."""
    goal = await _goal(cap=0.10)
    engine = _PricedEngine(price_per_step=0.09)
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    await repo.set_goal_status(goal["id"], "running", owner_id=TEST_USER_SUB)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "paused"
    assert engine.executed == ["step one"]


# ── routing survives a pause ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_continues_on_the_model_the_goal_started_with():
    """A budget is only meaningful if spend keeps being priced the same way:
    a resumed goal must not silently switch models."""
    seen: list[tuple[str | None, bool]] = []

    class _RoutingEngine(GoalEngine):
        async def _run_step(self, step, *, model=None, local_first=True, **kwargs):  # type: ignore[override]
            seen.append((model, local_first))
            return "ok", None

    goal = await _goal(cap=0, objective="routed goal", model="gpt-4o", local_first=False)
    # Resume paths call execute_goal with no routing arguments at all.
    final = await _RoutingEngine().execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    assert seen and all(entry == ("gpt-4o", False) for entry in seen), seen


@pytest.mark.asyncio
async def test_explicit_routing_still_overrides_the_stored_value():
    seen: list[str | None] = []

    class _RoutingEngine(GoalEngine):
        async def _run_step(self, step, *, model=None, **kwargs):  # type: ignore[override]
            seen.append(model)
            return "ok", None

    goal = await _goal(cap=0, objective="override goal", model="gpt-4o")
    await _RoutingEngine().execute_goal(
        goal["id"], owner_id=TEST_USER_SUB, model="llama3.2:1b"
    )
    assert seen and all(m == "llama3.2:1b" for m in seen)


# ── the queue's budget field (previously dead) ───────────────────────────────

@pytest.mark.asyncio
async def test_queue_refuses_a_task_with_no_budget_left():
    """QueuedTask.max_cost_usd used to be inert; a task submitted with an
    exhausted budget must now be refused instead of run."""
    queue = TaskQueue()
    ran = asyncio.Event()

    async def work():
        ran.set()

    await queue._execute(QueuedTask(
        name="broke-task", fn=work, mode=ExecutionMode.ON_DEMAND, max_cost_usd=0.0,
    ))
    assert not ran.is_set()

    await queue._execute(QueuedTask(
        name="funded-task", fn=work, mode=ExecutionMode.ON_DEMAND, max_cost_usd=1.0,
    ))
    assert ran.is_set()


@pytest.mark.asyncio
async def test_queue_reports_real_spend():
    """stats()['cost_spent_usd'] was always zero; it now reflects what ran."""
    queue = TaskQueue()

    async def spending_work():
        record_cost(0.07, "openai")

    assert queue.stats()["cost_spent_usd"] == 0
    await queue._execute(QueuedTask(
        name="spender", fn=spending_work, mode=ExecutionMode.ON_DEMAND,
    ))
    assert queue.stats()["cost_spent_usd"] == pytest.approx(0.07)


@pytest.mark.asyncio
async def test_remaining_budget_is_passed_to_queued_steps(monkeypatch):
    """Parallel steps carry the goal's remaining allowance to the queue."""
    submitted: list[float] = []
    from app.orchestration import task_queue as queue_module

    original_enqueue = queue_module.task_queue.enqueue

    async def spy(queued_task):
        submitted.append(queued_task.max_cost_usd)
        return await original_enqueue(queued_task)

    monkeypatch.setattr(queue_module.task_queue, "enqueue", spy)
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)

    plan = [{"title": "parallel", "steps": [
        {"instruction": "a", "depends_on": []},
        {"instruction": "b", "depends_on": []},
    ]}]
    goal = await _goal(plan, cap=2.0)
    await queue_module.task_queue.start()
    try:
        await _PricedEngine(price_per_step=0.01).execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    finally:
        await queue_module.task_queue.stop()
        await asyncio.sleep(1.1)

    assert submitted, "steps should have gone through the queue"
    assert all(amount == pytest.approx(2.0) for amount in submitted)


def test_uncapped_default_lets_a_task_run():
    assert QueuedTask(name="x", fn=None).max_cost_usd == UNCAPPED
    assert CostMeter().total_usd == 0.0


# ── API ──────────────────────────────────────────────────────────────────────

def test_budget_and_resume_endpoints_are_owner_scoped():
    from uuid import uuid4

    missing = str(uuid4())
    assert client.patch(f"/api/goals/{missing}/budget", json={"max_cost_usd": 5}).status_code == 404
    assert client.post(f"/api/goals/{missing}/resume", json={}).status_code == 404


def test_budget_endpoint_raises_the_cap():
    goal = asyncio.run(_goal(cap=0.10, objective="api budget goal"))
    res = client.patch(f"/api/goals/{goal['id']}/budget", json={"max_cost_usd": 4.5})
    assert res.status_code == 200
    assert res.json()["max_cost_usd"] == pytest.approx(4.5)
    assert client.get(f"/api/goals/{goal['id']}").json()["max_cost_usd"] == pytest.approx(4.5)


def test_budget_endpoint_rejects_a_negative_cap():
    goal = asyncio.run(_goal(cap=0.10, objective="api negative cap"))
    assert client.patch(f"/api/goals/{goal['id']}/budget", json={"max_cost_usd": -1}).status_code == 422


def test_resume_refuses_a_finished_goal():
    goal = asyncio.run(_goal(cap=0, objective="already done"))
    asyncio.run(repo.set_goal_status(goal["id"], "completed", owner_id=TEST_USER_SUB))
    res = client.post(f"/api/goals/{goal['id']}/resume", json={})
    assert res.status_code == 409
    assert "completed" in res.json()["detail"]
