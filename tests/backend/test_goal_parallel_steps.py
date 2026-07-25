"""Parallel goal steps through the task queue (capability map U2).

The DoD: a goal with two independent steps completes measurably faster than
serial, and both results appear in the goal record. Rather than asserting an
absolute wall-clock number (flaky on a loaded runner), the same goal is run
twice — once pinned serial, once parallel — and the two durations compared.

Also covers what must NOT be parallelized (dependent steps, steps of a later
task), that the steps really are submitted to the shared task queue, the
in-process fallback when no worker is draining that queue, and that a failure
inside a batch still replans.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

import pytest

from app.agents.goal_engine import GoalEngine
from app.core.config import settings
from app.db.repositories import repo
from app.orchestration.task_queue import task_queue

from conftest import TEST_USER_SUB

STEP_DELAY = 0.4

TWO_INDEPENDENT = [{"title": "research", "steps": [
    {"instruction": "research topic A", "depends_on": []},
    {"instruction": "research topic B", "depends_on": []},
]}]


class _SlowEngine(GoalEngine):
    """Engine whose steps take real time, so parallelism is observable.

    Also records peak concurrency, which is how the cap is verified.
    """

    def __init__(self, delay: float = STEP_DELAY, fail_instructions: set[str] | None = None):
        super().__init__()
        self.delay = delay
        self.executed: list[str] = []
        self.peak_concurrency = 0
        self._active = 0
        self._fail = fail_instructions or set()

    async def _run_step(self, step, **kwargs):  # type: ignore[override]
        self._active += 1
        self.peak_concurrency = max(self.peak_concurrency, self._active)
        try:
            await asyncio.sleep(self.delay)
            self.executed.append(step["instruction"])
            if step["instruction"] in self._fail:
                return "", "tool exploded"
            return f"result of {step['instruction']}", None
        finally:
            self._active -= 1


async def _new_goal(plan, objective="parallel objective"):
    return await repo.create_goal(
        objective, plan, project_id="default", owner_id=TEST_USER_SUB, status="running"
    )


def _results(goal: dict) -> dict[str, str]:
    return {s["instruction"]: s["result"] for t in goal["tasks"] for s in t["steps"]}


@pytest.fixture(autouse=True)
def _fast_stall_guard(monkeypatch):
    """Keep the stall guard short so a regression fails fast.

    In production the guard is generous (5 minutes) because a queued step may
    legitimately wait behind other work; in tests a stalled queue should be a
    quick failure, not a five-minute hang.
    """
    monkeypatch.setattr(settings, "goal_parallel_timeout_seconds", 10.0)


@asynccontextmanager
async def running_queue():
    """The real worker loop, started for the block and stopped afterwards."""
    await task_queue.start()
    try:
        yield task_queue
    finally:
        await task_queue.stop()
        # The loop blocks up to 1s in queue.get(); let it exit before the
        # test's event loop closes.
        await asyncio.sleep(1.1)


# ── the U2 definition of done ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_independent_steps_beat_serial_and_both_results_land(monkeypatch):
    """U2 DoD: parallel execution of two independent steps is measurably
    faster than serial, and both results appear in the goal record."""
    async with running_queue():
        # ── serial baseline ──
        monkeypatch.setattr(settings, "goal_max_parallel_steps", 1)
        serial_goal = await _new_goal(TWO_INDEPENDENT, "serial baseline")
        serial_engine = _SlowEngine()
        start = time.perf_counter()
        serial_final = await serial_engine.execute_goal(serial_goal["id"], owner_id=TEST_USER_SUB)
        serial_seconds = time.perf_counter() - start

        assert serial_engine.peak_concurrency == 1, "cap of 1 must stay strictly serial"
        assert serial_final["status"] == "completed"

        # ── parallel run of the same shape ──
        monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)
        parallel_goal = await _new_goal(TWO_INDEPENDENT, "parallel run")
        parallel_engine = _SlowEngine()
        start = time.perf_counter()
        parallel_final = await parallel_engine.execute_goal(
            parallel_goal["id"], owner_id=TEST_USER_SUB
        )
        parallel_seconds = time.perf_counter() - start

    assert parallel_engine.peak_concurrency == 2, "independent steps must overlap"
    assert parallel_final["status"] == "completed"

    # Measurably faster: serial pays both delays, parallel pays roughly one.
    assert parallel_seconds < serial_seconds * 0.75, (
        f"parallel {parallel_seconds:.2f}s was not measurably faster than "
        f"serial {serial_seconds:.2f}s"
    )

    # Both results joined back into goal state.
    assert _results(parallel_final) == {
        "research topic A": "result of research topic A",
        "research topic B": "result of research topic B",
    }
    assert sorted(parallel_engine.executed) == ["research topic A", "research topic B"]


@pytest.mark.asyncio
async def test_independent_steps_are_submitted_to_the_task_queue(monkeypatch):
    """The batch really goes through the shared queue — U2 gives that worker
    loop its first on-demand producer."""
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)
    submitted: list[str] = []
    original_enqueue = task_queue.enqueue

    async def spy_enqueue(queued_task):
        submitted.append(queued_task.name)
        return await original_enqueue(queued_task)

    monkeypatch.setattr(task_queue, "enqueue", spy_enqueue)

    goal = await _new_goal(TWO_INDEPENDENT)
    async with running_queue():
        final = await _SlowEngine(delay=0.05).execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert len(submitted) == 2, f"expected two queue submissions, got {submitted!r}"
    assert all(name.startswith("goal-step:") for name in submitted)
    assert final["status"] == "completed"


# ── what must not be parallelized ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dependent_steps_are_not_batched():
    goal = await _new_goal([{"title": "chain", "steps": [
        {"instruction": "first", "depends_on": []},
        {"instruction": "second", "depends_on": [0]},
    ]}])
    batch = await repo.runnable_step_batch(goal["id"], owner_id=TEST_USER_SUB, limit=4)
    assert [s["instruction"] for s in batch] == ["first"]


@pytest.mark.asyncio
async def test_steps_of_a_later_task_are_not_started_early():
    """Tasks read as ordered phases, so batching never crosses a task."""
    goal = await _new_goal([
        {"title": "phase one", "steps": [{"instruction": "a", "depends_on": []}]},
        {"title": "phase two", "steps": [{"instruction": "b", "depends_on": []}]},
    ])
    batch = await repo.runnable_step_batch(goal["id"], owner_id=TEST_USER_SUB, limit=4)
    assert [s["instruction"] for s in batch] == ["a"]


@pytest.mark.asyncio
async def test_batch_is_capped_by_configuration(monkeypatch):
    goal = await _new_goal([{"title": "wide", "steps": [
        {"instruction": f"step {i}", "depends_on": []} for i in range(5)
    ]}])
    batch = await repo.runnable_step_batch(goal["id"], owner_id=TEST_USER_SUB, limit=3)
    assert len(batch) == 3

    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)
    engine = _SlowEngine(delay=0.05)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)
    assert final["status"] == "completed"
    assert engine.peak_concurrency <= 2, "the cap must hold across batches"
    assert len(engine.executed) == 5


# ── fallback and failure handling ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_runs_in_process_when_no_worker_is_draining_the_queue(monkeypatch):
    """With the queue stopped, the engine must still execute the batch (and
    honour the cap) instead of waiting on a task nothing will run."""
    assert not task_queue.is_running, "this test needs the queue stopped"
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)

    goal = await _new_goal(TWO_INDEPENDENT)
    engine = _SlowEngine()
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    assert engine.peak_concurrency == 2
    assert len(_results(final)) == 2


@pytest.mark.asyncio
async def test_stalled_queue_falls_back_instead_of_hanging_the_goal(monkeypatch):
    """If the queue accepts submissions but never runs them, the guard expires
    and the engine finishes the batch itself — each step exactly once."""
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)
    monkeypatch.setattr(settings, "goal_parallel_timeout_seconds", 1.0)

    async def blackhole_enqueue(_queued_task):
        return "swallowed"

    monkeypatch.setattr(task_queue, "enqueue", blackhole_enqueue)
    monkeypatch.setattr(type(task_queue), "is_running", property(lambda _self: True))

    goal = await _new_goal(TWO_INDEPENDENT)
    engine = _SlowEngine(delay=0.05)
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    # Claim-once: the fallback ran each step, and nothing ran twice.
    assert sorted(engine.executed) == ["research topic A", "research topic B"]
    assert len(_results(final)) == 2


@pytest.mark.asyncio
async def test_worker_survives_an_unexpected_error_and_keeps_draining():
    """The worker is the queue's only consumer; an exception in one cycle must
    not leave the queue permanently undrained."""
    async with running_queue():
        boom_raised = asyncio.Event()
        ran = asyncio.Event()

        async def exploding_task():
            boom_raised.set()
            raise RuntimeError("unexpected worker-cycle failure")

        async def good_task():
            ran.set()

        from app.orchestration.task_queue import ExecutionMode, QueuedTask

        await task_queue.enqueue(QueuedTask(
            name="boom", fn=exploding_task, mode=ExecutionMode.ON_DEMAND, priority=1,
        ))
        await asyncio.wait_for(boom_raised.wait(), timeout=5)
        await task_queue.enqueue(QueuedTask(
            name="after-boom", fn=good_task, mode=ExecutionMode.ON_DEMAND, priority=1,
        ))
        # The queue still drains after the failure.
        await asyncio.wait_for(ran.wait(), timeout=10)


@pytest.mark.asyncio
async def test_failure_in_a_batch_replans_and_keeps_the_sibling_result(monkeypatch):
    """One step of a parallel batch failing must not discard the sibling that
    succeeded, and the goal continues through a replan."""
    import app.agents.goal_engine as engine_module

    seen: list[list[str]] = []

    async def fake_replan(objective, *, failed_instruction, error, completed, remaining, **kwargs):
        seen.append([c["instruction"] for c in completed])
        return [{"instruction": "recovered step", "depends_on": []}]

    monkeypatch.setattr(engine_module, "replan", fake_replan)
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)

    goal = await _new_goal(TWO_INDEPENDENT)
    engine = _SlowEngine(delay=0.05, fail_instructions={"research topic B"})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    statuses = {s["instruction"]: s["status"] for t in final["tasks"] for s in t["steps"]}
    assert statuses["research topic A"] == "completed"
    assert statuses["research topic B"] == "failed"
    assert statuses["recovered step"] == "completed"
    # The successful sibling's result survived and was visible to the replan.
    assert _results(final)["research topic A"] == "result of research topic A"
    assert seen and "research topic A" in seen[0]


@pytest.mark.asyncio
async def test_resume_after_restart_still_works_with_parallel_batches(monkeypatch):
    """U1's durability holds under U2: a goal interrupted mid-batch resumes
    without re-running the step that already completed."""
    monkeypatch.setattr(settings, "goal_max_parallel_steps", 2)
    goal = await _new_goal([{"title": "wide", "steps": [
        {"instruction": "done already", "depends_on": []},
        {"instruction": "left running", "depends_on": []},
    ]}], "interrupted parallel goal")
    gid = goal["id"]

    # Simulate the kill: one step finished, its sibling left mid-flight.
    batch = await repo.runnable_step_batch(gid, owner_id=TEST_USER_SUB, limit=2)
    finished = next(s for s in batch if s["instruction"] == "done already")
    running = next(s for s in batch if s["instruction"] == "left running")
    await repo.start_step(finished["id"], owner_id=TEST_USER_SUB)
    await repo.finish_step(
        finished["id"], status="completed", result="original result", owner_id=TEST_USER_SUB
    )
    await repo.start_step(running["id"], owner_id=TEST_USER_SUB)

    engine = _SlowEngine(delay=0.05)
    resumed = await engine.resume_unfinished_goals()
    assert gid in resumed

    assert engine.executed.count("done already") == 0, "completed work must not repeat"
    assert "left running" in engine.executed
    final = await repo.get_goal(gid, owner_id=TEST_USER_SUB)
    assert final["status"] == "completed"
    assert _results(final)["done already"] == "original result"
