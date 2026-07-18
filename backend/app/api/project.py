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
    """Conversation list for the project (session id + title + preview + last activity)."""
    rows = await repo.list_chat_sessions(project_id, owner_id=_user["sub"])
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


class SessionUpdate(BaseModel):
    title: str


@router.patch("/{project_id}/sessions/{session_id}")
async def rename_session(project_id: str, session_id: str, payload: SessionUpdate, _user=user_or_above):
    """Rename a conversation. 404 for non-owners and unknown sessions."""
    ok = await repo.rename_chat_session(project_id, session_id, payload.title, owner_id=_user["sub"])
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "title": payload.title.strip()[:255]}


@router.delete("/{project_id}/sessions/{session_id}")
async def delete_session(project_id: str, session_id: str, _user=user_or_above):
    """Delete a conversation (messages + summary + session row). 404 for
    non-owners and unknown sessions."""
    ok = await repo.delete_chat_session(project_id, session_id, owner_id=_user["sub"])
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.get("/{project_id}/search")
async def search_project_chats(project_id: str, q: str = "", _user=user_or_above):
    """Owner-scoped substring search over the project's chat messages."""
    rows = await repo.search_chat_messages(project_id, q, owner_id=_user["sub"])
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows
