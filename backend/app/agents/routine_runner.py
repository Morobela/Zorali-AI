"""User-configurable routines: a schedule plus a prompt, run without asking.

The deployment's own routines — the reality scan, the nightly self-check, the
nightly backup — are compiled in. This hands the same idea to an account:
"every morning, tell me what changed in my project."

Two pieces:

- :func:`run_routine` executes one routine's prompt through the same tool loop
  a chat turn uses, as that routine's owner and with that owner's role, so
  every gate already in the registry applies unchanged. What it produces
  becomes a notification.
- :func:`tick` finds routines whose time has come and runs them. It is
  registered once as a CONTINUOUS task and polls Postgres, so a restart loses
  nothing and a routine created a second ago is picked up without touching the
  queue — the same reasoning that lets goals resume on boot.

**Bounds.** A user-defined thing that runs unattended and spends money needs
them, and they are not decoration:

- every run is metered against a ceiling (``routine_max_cost_usd``, or the
  routine's own smaller one), and a run that exceeds it disables the routine.
  The cap bounds *repetition* rather than interrupting a run mid-flight — one
  turn's spend is already bounded by the tool loop's call limit
- an interval has a floor, enforced at the API, so "every 10 seconds" is not a
  legal way to bill a deployment continuously
- consecutive failures disable the routine and say why, because one that fails
  hourly and notifies hourly trains its owner to ignore the channel
- a run acts as its owner. It cannot reach anything that owner could not reach
  from a chat window, and it has no write-capable tool the registry would not
  already have refused.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.agents.chat_tools import run_chat_tool_loop
from app.core.config import settings
from app.db.repositories import repo
from app.inference.cost_meter import cost_meter
from app.models.llm import stream_llm

_log = logging.getLogger(__name__)

# How much of a routine's answer rides in the notification body. The full text
# stays on the run record.
NOTIFICATION_CHARS = 1200

SYSTEM_PROMPT = (
    "You are Zorali, running a scheduled routine its owner set up earlier. "
    "Nobody is waiting on this answer, so be brief and lead with what changed "
    "or what matters. If there is nothing worth reporting, say exactly that in "
    "one line rather than padding."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def next_run_after(routine: dict, *, now: datetime | None = None) -> datetime:
    """When this routine should run next.

    ``daily`` lands on the next occurrence of its hour; ``interval`` counts
    forward from now rather than from the scheduled time, so a routine that
    was late does not immediately fire again to catch up.
    """
    moment = now or _utc_now()
    if routine.get("schedule_kind") == "daily":
        hour = int(routine.get("hour_utc", 8))
        candidate = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= moment:
            candidate += timedelta(days=1)
        return candidate
    seconds = max(
        int(routine.get("interval_seconds") or settings.routine_min_interval_seconds),
        settings.routine_min_interval_seconds,
    )
    return moment + timedelta(seconds=seconds)


def _cap_for(routine: dict) -> float:
    """A routine's spend ceiling for one run.

    0 means "use the deployment default" — never "uncapped". An unattended
    prompt with no ceiling is the failure mode this feature has to avoid.
    """
    declared = float(routine.get("max_cost_usd") or 0.0)
    if declared <= 0:
        return settings.routine_max_cost_usd
    return min(declared, settings.routine_max_cost_usd)


async def _answer(routine: dict, owner_id: str) -> str:
    """One turn of the normal tool loop, run as the routine's owner."""
    collected: list[str] = []

    async def emit_token(text: str) -> None:
        collected.append(text)

    async def emit_event(_frame: dict) -> None:
        # A routine has no socket to stream tool steps to; the run record and
        # the notification carry the outcome.
        return None

    await run_chat_tool_loop(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": routine["prompt"]},
        ],
        stream=lambda msgs: stream_llm(msgs),
        emit_token=emit_token,
        emit_event=emit_event,
        caller=owner_id,
        # Routines run at the least privilege the app has. A scheduled prompt
        # is exactly the thing that should not be able to call an admin tool,
        # whoever owns it.
        caller_role="user",
        project_id=routine.get("project_id") or "default",
    )
    return "".join(collected).strip()


async def run_routine(routine: dict, *, owner_id: str) -> dict:
    """Execute one routine and notify its owner. Never raises.

    On the cap: a run is measured, not interrupted. One turn's spend is
    already bounded by the tool loop's call limit, so the risk a recurring
    routine adds is *repetition* — and that is what the cap stops. A run that
    exceeds it disables the routine and says so, rather than being killed
    halfway and leaving a half-answer nobody can act on.
    """
    run = await repo.start_routine_run(routine["id"], owner_id=owner_id)
    cap = _cap_for(routine)
    status, result, error = "completed", "", ""

    with cost_meter() as meter:
        try:
            result = await _answer(routine, owner_id)
            if not result:
                status, error = "failed", "the routine produced no output"
        except Exception as exc:  # a broken routine must not stop the ticker
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            _log.warning("Routine %s failed: %s", routine["id"], error)

    over_budget = meter.total_usd > cap
    if over_budget:
        status = "over_budget"
        error = (
            f"this run spent ${meter.total_usd:.4f}, over its ${cap:.4f} ceiling"
        )

    updated = await repo.finish_routine_run(
        run["id"], routine["id"], owner_id=owner_id,
        status=status, result=result, error=error,
        cost_usd=meter.total_usd,
        next_run_at=next_run_after(routine),
        # One overspend is enough: a routine that costs too much once will
        # cost too much every time, so it does not get two more chances.
        failure_limit=1 if over_budget else settings.routine_failure_limit,
    )

    await _notify(routine, owner_id, status=status, result=result, error=error,
                  disabled_reason=(updated or {}).get("disabled_reason", ""))
    return {"status": status, "result": result, "error": error, "cost_usd": meter.total_usd}


async def _notify(routine: dict, owner_id: str, *, status: str, result: str,
                  error: str, disabled_reason: str) -> None:
    """Tell the owner. Unlike the backup routine, success is not silent here —
    a routine's whole purpose is to report, so a quiet success would mean the
    feature did nothing."""
    try:
        if status == "completed":
            await repo.create_notification(
                owner_id, "routine", routine["name"], body=result[:NOTIFICATION_CHARS],
            )
            return
        body = error
        if disabled_reason:
            body = f"{error}\n\nThis routine is now disabled: {disabled_reason}"
        await repo.create_notification(
            owner_id, "routine_failed", f"{routine['name']} failed", body=body,
        )
    except Exception:
        # Losing the notification must not lose the run record.
        _log.warning("Could not notify owner of routine %s", routine["id"])


async def tick() -> dict:
    """Run every routine that is due. Registered as one CONTINUOUS task."""
    if not settings.routines_enabled:
        return {"ran": 0}
    from app.core.caller import SYSTEM

    try:
        due = await repo.due_routines(owner_id=SYSTEM)
    except Exception as exc:
        _log.warning("Routine sweep failed: %s", exc)
        return {"ran": 0, "error": str(exc)}

    ran = 0
    for routine in due:
        owner_id = routine.get("owner_id")
        if not owner_id:
            continue
        await run_routine(routine, owner_id=owner_id)
        ran += 1
    return {"ran": ran}
