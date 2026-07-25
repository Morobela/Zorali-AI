"""Durable goal engine (capability map U1).

Executes a persisted plan step by step. Every transition is written to
Postgres before the next step starts, so the work does not die with the
process: on boot ``resume_unfinished_goals`` picks up goals still marked
``running`` and continues from the first step that has not completed.

Steps run through the existing ``run_chat_tool_loop`` — the same
model-driven tool loop the chat path uses, extended with goal context, not
replaced. On failure the planner is asked to rewrite the remaining steps
(the message-level retry pattern in ``agents/nodes.py``, promoted to plan
level); if it declines, the goal fails with the error recorded.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Awaitable, Callable

from app.agents.chat_tools import run_chat_tool_loop
from app.agents.goal_planner import plan_goal, replan
from app.agents.nodes import _build_tools_system_prompt
from app.agents.reasoning import strip_think
from app.core.config import settings
from app.db.repositories import repo
from app.models.llm import stream_llm
from app.orchestration.task_queue import ExecutionMode, QueuedTask, task_queue

EmitFn = Callable[[dict], Awaitable[None]]


class _Claim:
    """One-shot claim so a step can never be executed twice.

    Both the queued task and the engine's timeout fallback try to run a step;
    exactly one wins the claim and the other returns immediately.
    """

    __slots__ = ("taken",)

    def __init__(self) -> None:
        self.taken = False

    def take(self) -> bool:
        if self.taken:
            return False
        self.taken = True
        return True

# How much of an earlier step's result is carried into later steps.
_RESULT_CONTEXT_CHARS = 1200

_STEP_SYSTEM_PROMPT = """You are Zorali executing one step of a larger plan.

Do exactly the step you are given — not the whole objective — and reply with
the result of that step only. Be concise and concrete. Results of earlier
steps are provided as context; use them instead of redoing that work."""


async def _noop_emit(_event: dict) -> None:
    return None


class GoalEngine:
    """Runs and resumes durable goals."""

    async def start_goal(
        self,
        objective: str,
        *,
        project_id: str,
        session_id: str = "",
        owner_id: str,
        caller_role: str = "user",
        emit: EmitFn | None = None,
        emit_token: Callable[[str], Awaitable[None]] | None = None,
        model: str | None = None,
        local_first: bool = True,
    ) -> dict:
        """Plan an objective, persist the plan, then execute it."""
        emit = emit or _noop_emit
        plan = await plan_goal(objective, model=model, local_first=local_first)
        goal = await repo.create_goal(
            objective, plan, project_id=project_id, session_id=session_id,
            owner_id=owner_id, status="running",
        )
        await self._emit_goal(emit, goal["id"], "plan", owner_id=owner_id)
        return await self.execute_goal(
            goal["id"], owner_id=owner_id, caller_role=caller_role, emit=emit,
            emit_token=emit_token, model=model, local_first=local_first,
        )

    async def execute_goal(
        self,
        goal_id: str,
        *,
        owner_id: str,
        caller_role: str = "user",
        emit: EmitFn | None = None,
        emit_token: Callable[[str], Awaitable[None]] | None = None,
        model: str | None = None,
        local_first: bool = True,
    ) -> dict:
        """Drive a persisted goal to completion (or failure).

        Returns the final goal record. Safe to call on a partially executed
        goal — that is exactly what resume does.
        """
        emit = emit or _noop_emit
        goal = await repo.get_goal(goal_id, owner_id=owner_id)
        if goal is None:
            return {}
        objective = goal["objective"]
        project_id = goal["project_id"]

        executed = 0
        replans = 0
        while executed < settings.goal_max_steps:
            batch = await repo.runnable_step_batch(
                goal_id, owner_id=owner_id, limit=settings.goal_max_parallel_steps
            )
            if not batch:
                break

            # Independent steps of the same task run together through the
            # orchestration queue (U2); a lone step runs inline, keeping the
            # common case free of queue overhead and able to stream tokens.
            outcomes = await self._run_batch(
                batch, objective=objective, project_id=project_id, goal_id=goal_id,
                owner_id=owner_id, caller_role=caller_role, emit=emit,
                emit_token=emit_token, model=model, local_first=local_first,
            )
            executed += len(batch)

            failures = [(step, error) for step, error in outcomes if error is not None]
            if not failures:
                continue
            # Replan from the first failure; steps that succeeded alongside it
            # keep their results, and the replan sees them as completed.
            step, error = failures[0]

            if replans >= settings.goal_max_replans:
                return await self._fail_goal(
                    goal_id, f"step failed and replan budget exhausted: {error}",
                    owner_id=owner_id, emit=emit,
                )

            completed, remaining = await self._plan_context(goal_id, step, owner_id=owner_id)
            new_steps = await replan(
                objective, failed_instruction=step["instruction"], error=error,
                completed=completed, remaining=remaining, model=model, local_first=local_first,
            )
            replans += 1
            if not new_steps:
                return await self._fail_goal(
                    goal_id, f"step failed with no viable replan: {error}",
                    owner_id=owner_id, emit=emit,
                )
            await repo.replace_remaining_steps(step["task_id"], new_steps, owner_id=owner_id)
            await self._emit_goal(emit, goal_id, "replanned", owner_id=owner_id)

        final = await repo.get_goal(goal_id, owner_id=owner_id)
        if final is None:
            return {}
        unfinished = [
            s for t in final["tasks"] for s in t["steps"]
            if s["status"] in ("pending", "running")
        ]
        if unfinished:
            # Only reachable via the step ceiling — a runaway replan loop.
            return await self._fail_goal(
                goal_id, f"step ceiling reached ({settings.goal_max_steps}) with work remaining",
                owner_id=owner_id, emit=emit,
            )
        await repo.set_goal_status(goal_id, "completed", owner_id=owner_id)
        await self._emit_goal(emit, goal_id, "goal_completed", owner_id=owner_id)
        return await repo.get_goal(goal_id, owner_id=owner_id) or {}

    async def resume_unfinished_goals(self, *, emit: EmitFn | None = None) -> list[str]:
        """Continue every goal interrupted by a restart.

        This is the Ultron property from the capability map: the work does not
        die with the body. Each goal is resumed under its own owner's scope,
        never a system-wide bypass. Returns the resumed goal ids.
        """
        resumed: list[str] = []
        for goal in await repo.list_unfinished_goals():
            owner_id = goal["owner_id"]
            try:
                # Steps left mid-flight by the killed process have no result,
                # so they must run again.
                await repo.reset_stuck_steps(goal["id"], owner_id=owner_id)
                await repo.set_goal_status(goal["id"], "running", owner_id=owner_id)
                await self.execute_goal(goal["id"], owner_id=owner_id, emit=emit)
                resumed.append(goal["id"])
            except Exception:
                # One poisoned goal must not stop the others from resuming.
                continue
        return resumed

    # ── internals ───────────────────────────────────────────────────────────

    async def _run_batch(
        self,
        batch: list[dict],
        *,
        emit: EmitFn,
        emit_token: Callable[[str], Awaitable[None]] | None,
        **step_kwargs,
    ) -> list[tuple[dict, str | None]]:
        """Execute one batch of independent steps; returns (step, error) pairs.

        A single step runs inline (streaming its tokens, exactly as before U2).
        A batch of two or more is submitted to the shared ``task_queue`` — its
        first on-demand producer — and awaited. Token streaming is suppressed
        for parallel batches: two steps writing into one bubble would interleave
        into nonsense, so progress shows through ``goal_update`` frames instead.
        """
        if len(batch) == 1:
            step = batch[0]
            return [(step, await self._run_one(
                step, emit=emit, emit_token=emit_token, **step_kwargs
            ))]

        claims = {step["id"]: _Claim() for step in batch}
        outcomes: dict[str, str | None] = {}

        async def _work(step: dict) -> None:
            if not claims[step["id"]].take():
                return
            outcomes[step["id"]] = await self._run_one(
                step, emit=emit, emit_token=None, **step_kwargs
            )

        if task_queue.is_running:
            done_events = {step["id"]: asyncio.Event() for step in batch}

            async def _queued(step: dict) -> None:
                try:
                    await _work(step)
                finally:
                    done_events[step["id"]].set()

            for step in batch:
                await task_queue.enqueue(QueuedTask(
                    name=f"goal-step:{step['id'][:8]}",
                    fn=partial(_queued, step),
                    mode=ExecutionMode.ON_DEMAND,
                    priority=4,
                ))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in done_events.values())),
                    timeout=settings.goal_parallel_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # A stalled queue must never hang a goal: finish the unclaimed
                # steps here. ``_Claim`` guarantees no step runs twice.
                await asyncio.gather(*(
                    _work(step) for step in batch if not claims[step["id"]].taken
                ))
        else:
            # No worker draining the queue (a process that never ran startup,
            # or one shutting down): run the batch here, same concurrency cap.
            limiter = asyncio.Semaphore(settings.goal_max_parallel_steps)

            async def _limited(step: dict) -> None:
                async with limiter:
                    await _work(step)

            await asyncio.gather(*(_limited(step) for step in batch))

        return [(step, outcomes.get(step["id"], "step did not run")) for step in batch]

    async def _run_one(
        self,
        step: dict,
        *,
        goal_id: str,
        owner_id: str,
        emit: EmitFn,
        emit_token: Callable[[str], Awaitable[None]] | None,
        **run_kwargs,
    ) -> str | None:
        """Mark a step running, execute it, record the outcome. Returns the
        error string, or ``None`` on success."""
        await repo.start_step(step["id"], owner_id=owner_id)
        await self._emit_goal(emit, goal_id, "step_started", owner_id=owner_id, step=step)

        result, error = await self._run_step(
            step, goal_id=goal_id, owner_id=owner_id, emit=emit,
            emit_token=emit_token, **run_kwargs,
        )
        if error is None:
            await repo.finish_step(
                step["id"], status="completed", result=result, owner_id=owner_id
            )
            await self._emit_goal(emit, goal_id, "step_completed", owner_id=owner_id, step=step)
        else:
            await repo.finish_step(
                step["id"], status="failed", error=error, owner_id=owner_id
            )
            await self._emit_goal(emit, goal_id, "step_failed", owner_id=owner_id, step=step)
        return error

    async def _run_step(
        self,
        step: dict,
        *,
        objective: str,
        project_id: str,
        goal_id: str,
        owner_id: str,
        caller_role: str,
        emit: EmitFn,
        emit_token: Callable[[str], Awaitable[None]] | None,
        model: str | None,
        local_first: bool,
    ) -> tuple[str, str | None]:
        """Execute one step through the shared chat tool loop.

        Returns ``(result_text, error)`` — every failure comes back as an
        error string so the caller can record it and replan.
        """
        prior = await self._completed_results(goal_id, owner_id=owner_id)
        messages: list[dict] = [{"role": "system", "content": _STEP_SYSTEM_PROMPT}]
        messages.append({
            "role": "system",
            "content": f"Overall objective: {objective}",
        })
        if prior:
            context = "\n\n".join(
                f"[{i + 1}] {p['instruction']}\n{p['result'][:_RESULT_CONTEXT_CHARS]}"
                for i, p in enumerate(prior)
            )
            messages.append({
                "role": "system",
                "content": "Results of completed steps:\n" + context,
            })
        tools_prompt = _build_tools_system_prompt()
        if tools_prompt:
            messages.append({
                "role": "system",
                "content": tools_prompt + (
                    f"\n\nThe current project_id for document_search is {project_id!r}."
                ),
            })
        messages.append({"role": "user", "content": step["instruction"]})

        collected: list[str] = []

        async def _collect(text: str) -> None:
            if not text:
                return
            collected.append(text)
            if emit_token is not None:
                await emit_token(text)

        try:
            await run_chat_tool_loop(
                messages,
                stream=lambda msgs: stream_llm(msgs, model=model, local_first=local_first),
                emit_token=_collect,
                emit_event=emit,
                caller=owner_id,
                caller_role=caller_role,
                project_id=project_id,
            )
        except Exception as exc:
            return "", f"{type(exc).__name__}: {exc}"

        result = strip_think("".join(collected)).strip()
        if not result:
            return "", "step produced no output"
        return result, None

    @staticmethod
    async def _completed_results(goal_id: str, *, owner_id: str) -> list[dict]:
        goal = await repo.get_goal(goal_id, owner_id=owner_id)
        if goal is None:
            return []
        return [
            {"instruction": s["instruction"], "result": s["result"]}
            for t in goal["tasks"] for s in t["steps"]
            if s["status"] == "completed" and s["result"]
        ]

    @staticmethod
    async def _plan_context(goal_id: str, failed_step: dict, *, owner_id: str) -> tuple[list, list]:
        """(completed steps, still-pending steps) for the replan prompt."""
        goal = await repo.get_goal(goal_id, owner_id=owner_id)
        if goal is None:
            return [], []
        completed, remaining = [], []
        for task in goal["tasks"]:
            for step in task["steps"]:
                if step["status"] == "completed":
                    completed.append({"instruction": step["instruction"], "result": step["result"]})
                elif step["status"] in ("pending", "running") and step["id"] != failed_step["id"]:
                    remaining.append({"instruction": step["instruction"]})
        return completed, remaining

    async def _fail_goal(
        self, goal_id: str, error: str, *, owner_id: str, emit: EmitFn
    ) -> dict:
        await repo.set_goal_status(goal_id, "failed", error=error, owner_id=owner_id)
        await self._emit_goal(emit, goal_id, "goal_failed", owner_id=owner_id)
        return await repo.get_goal(goal_id, owner_id=owner_id) or {}

    @staticmethod
    async def _emit_goal(
        emit: EmitFn, goal_id: str, event: str, *, owner_id: str, step: dict | None = None
    ) -> None:
        """Stream a ``goal_update`` frame carrying the whole goal snapshot.

        Sending the full checklist on every transition keeps the UI stateless
        and immune to a dropped frame. Never raises: a closed socket must not
        abort a goal that is otherwise progressing.
        """
        try:
            goal = await repo.get_goal(goal_id, owner_id=owner_id)
            if goal is None:
                return
            payload = {"type": "goal_update", "event": event, "goal": goal}
            if step is not None:
                payload["step_id"] = step["id"]
            await emit(payload)
        except Exception:
            return


goal_engine = GoalEngine()
