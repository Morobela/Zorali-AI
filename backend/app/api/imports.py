"""Repository import API (capability map U6).

``POST /api/project/{id}/import/github`` accepts a repository, returns 202
with an import id, and does the clone + ingestion in a background task. The
caller polls the import row for progress and per-file outcomes, exactly like
single-file upload polls ``indexing_status``.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.rbac import user_or_above
from app.db.repositories import repo
from app.ingestion.github_import import ImportError_, parse_repo, run_import, validate_ref

router = APIRouter(prefix="/api/project", tags=["imports"])


class GithubImportIn(BaseModel):
    # "owner/repo" or https://github.com/owner/repo
    repo: str = Field(min_length=1, max_length=512)
    ref: str | None = Field(default=None, max_length=255)
    # Optional PAT for a private repository. Used for this clone only: never
    # logged, never persisted, and scrubbed from error text.
    token: str | None = Field(default=None, max_length=512)


def _public_import(record: dict) -> dict:
    """Import rows never contain a token, but keep the response explicit."""
    return {k: v for k, v in record.items() if k != "token"}


@router.post("/{project_id}/import/github", status_code=202)
async def import_github(
    project_id: str,
    payload: GithubImportIn,
    background_tasks: BackgroundTasks,
    _user=user_or_above,
):
    if not settings.github_import_enabled:
        raise HTTPException(status_code=403, detail="Repository import is disabled")

    project = await repo.get_project(project_id, owner_id=_user["sub"])
    # A project the caller does not own is indistinguishable from a missing one.
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        owner, name = parse_repo(payload.repo)
        ref = validate_ref(payload.ref)
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = await repo.create_import(
        project_id=project_id, source=f"{owner}/{name}", ref=ref, owner_id=_user["sub"]
    )
    background_tasks.add_task(
        run_import, record["id"], owner=owner, name=name, ref=ref,
        token=payload.token, project_id=project_id, owner_id=_user["sub"],
    )
    return _public_import(record)


@router.get("/{project_id}/imports")
async def list_imports(project_id: str, limit: int = 50, _user=user_or_above):
    records = await repo.list_imports(
        owner_id=_user["sub"], project_id=project_id, limit=max(1, min(limit, 200))
    )
    return [_public_import(r) for r in records]


@router.get("/{project_id}/imports/{import_id}")
async def get_import(project_id: str, import_id: str, _user=user_or_above):
    record = await repo.get_import(import_id, owner_id=_user["sub"])
    if record is None or record["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Import not found")
    return _public_import(record)
