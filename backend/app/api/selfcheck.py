"""Self-check history and manual trigger (capability map U8).

Admin-gated: these runs describe the codebase, not one user's data. The
trigger exists so an operator does not have to wait for 03:00 to see what the
nightly run would say — it performs the same propose-only pass.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import settings
from app.core.rbac import admin_or_above
from app.db.repositories import repo
from app.selfcheck.runner import run_self_check

router = APIRouter(prefix="/api/self-check", tags=["self-check"])


@router.get("")
async def list_runs(limit: int = 20, _user=admin_or_above):
    return await repo.list_self_checks(limit=max(1, min(limit, 100)))


@router.post("/run", status_code=202)
async def trigger_run(background_tasks: BackgroundTasks, run_tests: bool | None = None, _user=admin_or_above):
    """Run the self-check now. Reports only — it never changes code."""
    if not settings.self_improvement_enabled:
        raise HTTPException(status_code=403, detail="Self-improvement is disabled")
    background_tasks.add_task(
        run_self_check,
        run_tests=settings.self_check_run_tests if run_tests is None else run_tests,
    )
    return {"status": "started"}
