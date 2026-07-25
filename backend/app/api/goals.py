"""Read API for durable goals (capability map U1).

Goals are created and driven by the WebSocket `goal` mode and the boot
resume sweep; this router exposes them for the UI (checklist after a
reconnect) and for operators inspecting what survived a restart.
"""
from fastapi import APIRouter, HTTPException

from app.core.rbac import user_or_above
from app.db.repositories import repo

router = APIRouter(prefix="/api/goals", tags=["goals"])


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
