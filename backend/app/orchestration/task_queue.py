"""
Resource-contention-aware task queue.
Patterns:
- Higgsfield: experiment queue that manages resource contention
- OpenJarvis: three execution modes (on-demand / scheduled / continuous)
- vLLM: priority queue with backpressure
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable
from uuid import uuid4
from app.orchestration.fault_tolerant import FaultTolerantExecutor, TaskSession


class ExecutionMode(str, Enum):
    ON_DEMAND = "on_demand"     # run immediately when capacity available
    SCHEDULED = "scheduled"     # run at a specific time / interval
    CONTINUOUS = "continuous"   # run repeatedly until cancelled


@dataclass
class QueuedTask:
    task_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    fn: Callable[[], Awaitable[Any]] = field(default_factory=lambda: None)
    priority: int = 5           # 1 (highest) → 10 (lowest)
    mode: ExecutionMode = ExecutionMode.ON_DEMAND
    run_at: float | None = None  # unix timestamp for scheduled tasks
    interval_s: float | None = None  # repeat interval for continuous tasks
    max_cost_usd: float = 10.0  # Higgsfield cost budget cap
    submitted_at: float = field(default_factory=time.time)

    def __lt__(self, other: "QueuedTask") -> bool:
        # Lower priority number = higher queue priority
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.submitted_at < other.submitted_at


class TaskQueue:
    """
    Priority task queue with resource tracking.
    Prevents resource contention by capping concurrent execution.
    """

    def __init__(self, max_concurrent: int = 4, cost_budget_usd: float = 50.0):
        self._max_concurrent = max_concurrent
        self._cost_budget = cost_budget_usd
        self._cost_spent: float = 0.0
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._active: dict[str, asyncio.Task] = {}
        self._history: list[TaskSession] = []
        self._running = False
        self._executor = FaultTolerantExecutor()

    @property
    def is_running(self) -> bool:
        """Whether the worker loop is live.

        Producers that await their submissions check this first: with no
        worker draining the queue (a process that never ran startup, or one
        already shutting down) an enqueued task would never execute, so the
        producer runs the work itself instead of waiting forever.
        """
        return self._running

    def _rebind_queue_if_needed(self) -> None:
        """Re-create the queue if it belongs to a previous event loop.

        ``asyncio.Queue`` binds itself to the first loop that awaits it and
        raises ``RuntimeError`` when touched from another one. The queue object
        is a module-level singleton, so a process that runs more than one loop
        (``asyncio.run`` twice, a test suite, an embedding script) would start
        a worker that dies on its first empty ``get()`` — leaving the queue
        permanently undrained. Pending items are carried across; the
        ``*_nowait`` calls used here never touch the loop binding.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if getattr(self._queue, "_loop", None) in (None, loop):
            return
        pending = []
        while not self._queue.empty():
            pending.append(self._queue.get_nowait())
        self._queue = asyncio.PriorityQueue()
        for item in pending:
            self._queue.put_nowait(item)

    async def start(self) -> None:
        if self._running:
            return
        self._rebind_queue_if_needed()
        self._running = True
        asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self._running = False

    async def enqueue(self, task: QueuedTask) -> str:
        await self._queue.put((task.priority, task.submitted_at, task))
        return task.task_id

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                if len(self._active) >= self._max_concurrent:
                    await asyncio.sleep(0.1)
                    continue
                _, _, task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if task.run_at and time.time() < task.run_at:
                    # Not yet due — requeue
                    await self._queue.put((task.priority, task.submitted_at, task))
                    await asyncio.sleep(0.5)
                    continue
                t = asyncio.create_task(self._execute(task))
                self._active[task.task_id] = t
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The worker is the queue's only consumer: if an unexpected
                # error killed this loop the queue would stay full forever
                # while `is_running` still claimed otherwise. Absorb it, pause
                # briefly, and keep draining.
                print(f"[Zorali] task queue worker error: {type(exc).__name__}: {exc}")
                await asyncio.sleep(0.2)

    async def _execute(self, task: QueuedTask) -> None:
        try:
            session = await self._executor.run(task.name, task.fn)
            self._history.append(session)
            if task.mode == ExecutionMode.CONTINUOUS and task.interval_s:
                await asyncio.sleep(task.interval_s)
                task.submitted_at = time.time()
                await self._queue.put((task.priority, task.submitted_at, task))
        finally:
            self._active.pop(task.task_id, None)

    def stats(self) -> dict:
        return {
            "queued": self._queue.qsize(),
            "active": len(self._active),
            "max_concurrent": self._max_concurrent,
            "cost_spent_usd": round(self._cost_spent, 4),
            "cost_budget_usd": self._cost_budget,
            "completed_tasks": len(self._history),
        }


task_queue = TaskQueue()
