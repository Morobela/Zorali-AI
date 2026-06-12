"""
Structured audit logging — every security-relevant action gets a record.
Inspired by TensorFlow's contextual save/restore pattern:
all state changes are captured with consistent metadata.
"""
from __future__ import annotations
import json
import time
import logging
from enum import Enum
from typing import Any
from dataclasses import dataclass, asdict

logger = logging.getLogger("zorali.audit")


class AuditEvent(str, Enum):
    AUTH_LOGIN = "auth.login"
    AUTH_FAILURE = "auth.failure"
    AUTH_TOKEN_ISSUED = "auth.token_issued"
    FILE_UPLOAD = "file.upload"
    FILE_ACCESS = "file.access"
    FILE_DELETE = "file.delete"
    TOOL_EXECUTED = "tool.executed"
    TOOL_BLOCKED = "tool.blocked"
    SKILL_INSTALLED = "skill.installed"
    SKILL_REMOVED = "skill.removed"
    RATE_LIMIT_HIT = "rate_limit.hit"
    PERMISSION_DENIED = "permission.denied"
    CHAT_SESSION = "chat.session"
    PROVIDER_SWITCH = "provider.switch"
    INFERENCE_COST = "inference.cost"
    LEARNING_CYCLE = "learning.cycle"


@dataclass
class AuditRecord:
    event: str
    actor: str
    resource: str
    outcome: str
    ts: float
    metadata: dict[str, Any]


class AuditLogger:
    """
    Append-only audit trail.
    Uses PyTorch-style weakref hook pattern: observers register once,
    receive every record without holding a hard reference to this logger.
    """

    def __init__(self):
        import weakref
        self._hooks: list[weakref.WeakMethod | Any] = []

    def add_hook(self, fn):
        """Register an observer for audit records (weakref-safe)."""
        import weakref
        try:
            self._hooks.append(weakref.WeakMethod(fn))
        except TypeError:
            self._hooks.append(lambda r: fn(r))

    def record(
        self,
        event: AuditEvent | str,
        actor: str = "system",
        resource: str = "-",
        outcome: str = "ok",
        **metadata: Any,
    ) -> None:
        rec = AuditRecord(
            event=str(event),
            actor=actor,
            resource=resource,
            outcome=outcome,
            ts=time.time(),
            metadata=metadata,
        )
        logger.info(json.dumps(asdict(rec)))
        dead = []
        for ref in self._hooks:
            fn = ref() if hasattr(ref, "__call__") and hasattr(ref, "__self__") else ref
            if fn is None:
                dead.append(ref)
            else:
                try:
                    fn(rec)
                except Exception:
                    pass
        for d in dead:
            self._hooks.remove(d)


audit = AuditLogger()
