"""Goals API (capability map U1, budget controls from U7).

Goals are created and driven by the WebSocket `goal` mode, the boot resume
sweep and the CI-failure routine. This router exposes them for the UI, and
gives the human the two moves a paused goal leaves open: resume it, or raise
its budget ceiling first.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.agents.goal_engine import goal_engine
from app.core.rbac import user_or_above
from app.db.repositories import repo

router = APIRouter(prefix="/api/goals", tags=["goals"])


class BudgetIn(BaseModel):
    # 0 removes the ceiling entirely.
    max_cost_usd: float = Field(ge=0.0, le=1000.0)


class ResumeIn(BaseModel):
    # Optionally raise the cap in the same call that resumes.
    max_cost_usd: float | None = Field(default=None, ge=0.0, le=1000.0)


@router.get("")
async def list_goals(project_id: str | None = None, limit: int = 50, _user=user_or_above):
    return await repo.list_goals(
        owner_id=_user["sub"], project_id=project_id, limit=max(1, min(limit, 200))
    )


@router.get("/{goal_id}")
async def get_goal(goal_id: str, _user=user_or_above):
    goal = await repo.get_goal(goal_id, owner_id=_user["sub"])
    # A goal owned by someone else behaves like a nonexistent one.
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.patch("/{goal_id}/budget")
async def set_budget(goal_id: str, payload: BudgetIn, _user=user_or_above):
    """Raise or lower a goal's spend ceiling without resuming it."""
    updated = await repo.set_goal_budget(goal_id, payload.max_cost_usd, owner_id=_user["sub"])
    if updated is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return updated


@router.post("/{goal_id}/resume")
async def resume_goal(
    goal_id: str, payload: ResumeIn, background_tasks: BackgroundTasks, _user=user_or_above
):
    """Resume a paused goal, optionally raising its cap first.

    Resuming without more budget is allowed and honest: the goal restarts,
    immediately re-checks its budget, and parks again — the pause is a
    decision point, not a trap.
    """
    goal = await repo.get_goal(goal_id, owner_id=_user["sub"])
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    if goal["status"] in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"Goal is already {goal['status']}")

    if payload.max_cost_usd is not None:
        await repo.set_goal_budget(goal_id, payload.max_cost_usd, owner_id=_user["sub"])

    await repo.set_goal_status(goal_id, "running", owner_id=_user["sub"])
    background_tasks.add_task(goal_engine.execute_goal, goal_id, owner_id=_user["sub"])
    return await repo.get_goal(goal_id, owner_id=_user["sub"])
