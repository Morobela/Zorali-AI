"""One opt-in recovery action (capability map U9).

The map allows exactly one: restart a compose service, **alert-only by
default**. Detection (U3) and alerting (U4) shipped first and have to be
trusted before anything is allowed to act on them, so the constraints here
are deliberately narrow:

- **Off unless switched on** (``RECOVERY_ACTIONS_ENABLED``). With it off this
  module reports what it *would* have done and changes nothing.
- **Allowlisted targets only.** ``RECOVERY_RESTART_SERVICES`` names what may
  be restarted; anything else is refused. ``postgres`` and ``backend`` are
  rejected outright even if listed — restarting the database out from under
  the process holding its connections, or the process running this code, is
  not recovery.
- **Cooldown per service.** A service that keeps dying must not become a
  restart loop; after one attempt a service is untouchable for
  ``RECOVERY_COOLDOWN_MINUTES``. A second failure inside that window stays an
  alert, which is what a human needs to see anyway.
- **Every attempt is audited** and reported in the same notification as the
  outage, so an action is never invisible.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time

from app.core.audit import audit, AuditEvent
from app.core.config import settings

_log = logging.getLogger(__name__)

# Restarting these from inside the backend is self-defeating or destructive,
# whatever the configuration says.
NEVER_RESTART = {"postgres", "db", "database", "backend", "api"}
_SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_RESTART_TIMEOUT_S = 60.0

# service name → unix timestamp of the last attempt.
_last_attempt: dict[str, float] = {}


def allowed_services() -> set[str]:
    configured = {
        s.strip() for s in (settings.recovery_restart_services or "").split(",") if s.strip()
    }
    return {s for s in configured if s not in NEVER_RESTART}


def _cooling_down(service: str, now: float) -> float:
    """Seconds left before ``service`` may be restarted again (0 when free)."""
    last = _last_attempt.get(service)
    if last is None:
        return 0.0
    remaining = (settings.recovery_cooldown_minutes * 60) - (now - last)
    return max(0.0, remaining)


def reset_cooldowns() -> None:
    """Test seam: forget every recorded attempt."""
    _last_attempt.clear()


async def attempt_restart(service: str) -> dict:
    """Try to restart one compose service.

    Returns ``{attempted, ok, reason}``. Never raises: recovery failing must
    not break the scan that noticed the outage.
    """
    now = time.time()
    result = {"service": service, "attempted": False, "ok": False, "reason": ""}

    if not settings.recovery_actions_enabled:
        result["reason"] = "recovery actions are disabled (alert-only)"
        return result
    if not _SERVICE_RE.match(service or ""):
        result["reason"] = "invalid service name"
        return result
    if service in NEVER_RESTART:
        result["reason"] = f"{service} is never restarted from inside the backend"
        return result
    if service not in allowed_services():
        result["reason"] = f"{service} is not in RECOVERY_RESTART_SERVICES"
        return result
    cooling = _cooling_down(service, now)
    if cooling > 0:
        result["reason"] = f"cooling down for another {cooling / 60:.1f} min"
        return result
    if shutil.which("docker") is None:
        result["reason"] = "docker is not available in this environment"
        return result

    _last_attempt[service] = now
    result["attempted"] = True
    audit.record(
        AuditEvent.TOOL_EXECUTED, actor="system", resource=f"recovery:restart:{service}",
        outcome="attempted",
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "restart", service,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_RESTART_TIMEOUT_S)
        if proc.returncode == 0:
            result["ok"] = True
            result["reason"] = "restarted"
        else:
            result["reason"] = out.decode(errors="replace").strip()[:200] or "restart failed"
    except asyncio.TimeoutError:
        result["reason"] = "restart timed out"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"

    audit.record(
        AuditEvent.TOOL_EXECUTED, actor="system", resource=f"recovery:restart:{service}",
        outcome="ok" if result["ok"] else "failed", detail=result["reason"][:200],
    )
    return result
