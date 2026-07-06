from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.config import settings
from app.core.rbac import user_or_above
from app.db.repositories import repo
from app.reality.project_scanner import status_report

router = APIRouter(prefix="/api/project")


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None


@router.get("/status")
async def project_status(_user=user_or_above):
    return status_report(settings.project_root)


@router.post("")
async def create_project(payload: ProjectCreate, _user=user_or_above):
    return await repo.create_project(payload.name, payload.description, owner_id=_user["sub"])


@router.get("")
async def list_projects(_user=user_or_above):
    return await repo.list_projects(owner_id=_user["sub"])


@router.patch("/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate, _user=user_or_above):
    """Update name/description/custom instructions (system_prompt)."""
    data = await repo.update_project(
        project_id,
        owner_id=_user["sub"],
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data


@router.get("/{project_id}/chats")
async def project_chats(project_id: str, session_id: str | None = None, _user=user_or_above):
    rows = await repo.list_chat_messages(project_id, session_id, owner_id=_user["sub"])
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/sessions")
async def project_sessions(project_id: str, _user=user_or_above):
    """Conversation list for the project (session id + preview + last activity)."""
    rows = await repo.list_chat_sessions(project_id, owner_id=_user["sub"])
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows
