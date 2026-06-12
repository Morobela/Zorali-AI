"""
Fault-tolerant task executor.
Patterns:
- OpenJarvis AgentExecutor: multi-turn executor with built-in retry + error classification
- Higgsfield: session-based tracking with status enum, benchmark gating
- OpenJarvis: error classify → retry / escalate / abort decision tree
"""
from __future__ import annotations
import asyncio
import time
from enum import Enum
from typing import Any, Callable, Awaitable
from dataclasses import dataclass, field
from uuid import uuid4
from app.core.audit import audit, AuditEvent


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    ABORTED = "aborted"


class ErrorClass(str, Enum):
    RECOVERABLE = "recoverable"   # retry with backoff
    ESCALATE = "escalate"         # report to user, stop retrying
    FATAL = "fatal"               # abort immediately


@dataclass
class TaskSession:
    task_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def update(self, status: TaskStatus, **kwargs) -> None:
        self.status = status
        self.updated_at = time.time()
        for k, v in kwargs.items():
            setattr(self, k, v)


def classify_error(exc: Exception) -> ErrorClass:
    """
    Pattern: OpenJarvis error classification for retry vs. escalate vs. abort.
    Network/timeout errors are recoverable; config/auth errors are fatal.
    """
    msg = str(exc).lower()
    fatal_signals = ("authentication", "unauthorized", "invalid api key", "not found", "permission denied")
    if any(s in msg for s in fatal_signals):
        return ErrorClass.FATAL
    recoverable_signals = ("timeout", "connection", "service unavailable", "503", "502", "429")
    if any(s in msg for s in recoverable_signals):
        return ErrorClass.RECOVERABLE
    return ErrorClass.ESCALATE


class FaultTolerantExecutor:
    """
    Executes async tasks with automatic retry and failure isolation.
    Each task gets its own TaskSession for status tracking.
    """

    def __init__(self):
        self._sessions: dict[str, TaskSession] = {}

    async def run(
        self,
        name: str,
        fn: Callable[[], Awaitable[Any]],
        max_attempts: int = 3,
        base_delay: float = 1.0,
    ) -> TaskSession:
        session = TaskSession(name=name, max_attempts=max_attempts)
        self._sessions[session.task_id] = session
        session.update(TaskStatus.RUNNING)

        for attempt in range(1, max_attempts + 1):
            session.attempts = attempt
            try:
                result = await fn()
                session.update(TaskStatus.COMPLETED, result=result)
                return session
            except Exception as exc:
                error_class = classify_error(exc)
                session.error = str(exc)

                if error_class == ErrorClass.FATAL or attempt == max_attempts:
                    final_status = TaskStatus.ABORTED if error_class == ErrorClass.FATAL else TaskStatus.FAILED
                    session.update(final_status)
                    audit.record(
                        AuditEvent.TOOL_BLOCKED,
                        resource=name,
                        outcome="failed",
                        attempt=attempt,
                        error=str(exc),
                        error_class=error_class.value,
                    )
                    return session

                delay = base_delay * (2 ** (attempt - 1))  # exponential backoff
                session.update(TaskStatus.RETRYING)
                await asyncio.sleep(delay)

        return session

    def get_session(self, task_id: str) -> TaskSession | None:
        return self._sessions.get(task_id)

    def active_sessions(self) -> list[dict]:
        return [
            {
                "task_id": s.task_id,
                "name": s.name,
                "status": s.status.value,
                "attempts": s.attempts,
                "error": s.error,
            }
            for s in self._sessions.values()
            if s.status in (TaskStatus.RUNNING, TaskStatus.RETRYING, TaskStatus.PENDING)
        ]


executor = FaultTolerantExecutor()
