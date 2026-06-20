from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings
from app.core.rbac import user_or_above
from app.db.repositories import repo
from app.reality.project_scanner import status_report

router = APIRouter(prefix="/api/project")


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


@router.get("/status")
async def project_status(_user=user_or_above):
    return status_report(settings.project_root)


@router.post("")
async def create_project(payload: ProjectCreate, _user=user_or_above):
    return repo.create_project(payload.name, payload.description)


@router.get("")
async def list_projects(_user=user_or_above):
    return repo.list_projects()


@router.get("/{project_id}/chats")
async def project_chats(project_id: str, session_id: str | None = None, _user=user_or_above):
    return repo.list_chat_messages(project_id, session_id)
