"""User-configurable routines: CRUD, run-now, and run history.

The bounds a routine has to respect are enforced here, at the edge, so a
routine that exists is already a legal one — the runner never has to defend
itself against a schedule the API should not have accepted.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.rbac import user_or_above
from app.db.repositories import repo

router = APIRouter(prefix="/api/routines", tags=["routines"])

SCHEDULE_KINDS = {"interval", "daily"}


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    project_id: str = "default"
    schedule_kind: str = "interval"
    interval_seconds: int = 3600
    hour_utc: int = Field(default=8, ge=0, le=23)
    max_cost_usd: float = Field(default=0.0, ge=0.0)

    @field_validator("schedule_kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in SCHEDULE_KINDS:
            raise ValueError(f"schedule_kind must be one of: {', '.join(sorted(SCHEDULE_KINDS))}")
        return value

    @field_validator("interval_seconds")
    @classmethod
    def _not_too_often(cls, value: int) -> int:
        # The floor is the difference between a routine and a money pump.
        floor = settings.routine_min_interval_seconds
        if value < floor:
            raise ValueError(f"interval_seconds must be at least {floor}")
        return value


class RoutinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    project_id: str | None = None
    schedule_kind: str | None = None
    interval_seconds: int | None = None
    hour_utc: int | None = Field(default=None, ge=0, le=23)
    enabled: bool | None = None
    max_cost_usd: float | None = Field(default=None, ge=0.0)

    @field_validator("schedule_kind")
    @classmethod
    def _known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in SCHEDULE_KINDS:
            raise ValueError(f"schedule_kind must be one of: {', '.join(sorted(SCHEDULE_KINDS))}")
        return value

    @field_validator("interval_seconds")
    @classmethod
    def _not_too_often(cls, value: int | None) -> int | None:
        floor = settings.routine_min_interval_seconds
        if value is not None and value < floor:
            raise ValueError(f"interval_seconds must be at least {floor}")
        return value


def _require_enabled() -> None:
    if not settings.routines_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Routines are disabled. Set ROUTINES_ENABLED=true to enable them.",
        )


@router.get("")
async def list_routines(_user=user_or_above):
    return await repo.list_routines(owner_id=_user["sub"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_routine(payload: RoutineIn, _user=user_or_above):
    _require_enabled()
    owner = _user["sub"]
    if await repo.count_enabled_routines(owner_id=owner) >= settings.routine_max_per_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You already have {settings.routine_max_per_user} enabled routines. "
                "Disable or delete one first."
            ),
        )
    from app.agents.routine_runner import next_run_after

    data = payload.model_dump()
    return await repo.create_routine(
        owner_id=owner, next_run_at=next_run_after(data), **data
    )


@router.get("/{routine_id}")
async def get_routine(routine_id: str, _user=user_or_above):
    routine = await repo.get_routine(routine_id, owner_id=_user["sub"])
    if routine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    return routine


@router.patch("/{routine_id}")
async def update_routine(routine_id: str, payload: RoutinePatch, _user=user_or_above):
    owner = _user["sub"]
    current = await repo.get_routine(routine_id, owner_id=owner)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    if payload.enabled is True and not current["enabled"]:
        _require_enabled()
        if await repo.count_enabled_routines(owner_id=owner) >= settings.routine_max_per_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You already have {settings.routine_max_per_user} enabled routines.",
            )
    fields = payload.model_dump(exclude_none=True)
    if {"schedule_kind", "interval_seconds", "hour_utc"} & set(fields):
        # A changed schedule takes effect from now, not from whenever the old
        # one happened to point at.
        from app.agents.routine_runner import next_run_after

        fields["next_run_at"] = next_run_after({**current, **fields})
    return await repo.update_routine(routine_id, owner_id=owner, **fields)


@router.delete("/{routine_id}")
async def delete_routine(routine_id: str, _user=user_or_above):
    if not await repo.delete_routine(routine_id, owner_id=_user["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    return {"deleted": routine_id}


@router.post("/{routine_id}/run")
async def run_now(routine_id: str, _user=user_or_above):
    """Run a routine immediately — the way to find out whether it works
    without waiting for its schedule."""
    _require_enabled()
    owner = _user["sub"]
    routine = await repo.get_routine(routine_id, owner_id=owner)
    if routine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    from app.agents.routine_runner import run_routine

    return await run_routine(routine, owner_id=owner)


@router.get("/{routine_id}/runs")
async def list_runs(routine_id: str, limit: int = 20, _user=user_or_above):
    owner = _user["sub"]
    if await repo.get_routine(routine_id, owner_id=owner) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    return await repo.list_routine_runs(routine_id, owner_id=owner, limit=max(1, min(limit, 100)))
