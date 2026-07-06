from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.core.config import settings
from app.core.rbac import admin_or_above, user_or_above
from app.db.repositories import repo

router = APIRouter(prefix='/api/artifacts')


class ArtifactCreate(BaseModel):
    project_id: str
    name: str
    content: str


class ArtifactUpdate(BaseModel):
    content: str


@router.post('')
async def create_artifact(payload: ArtifactCreate, _user=user_or_above):
    try:
        return await repo.create_artifact(payload.project_id, payload.name, payload.content, owner_id=_user["sub"])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail='Project not found') from exc


@router.get('')
async def list_artifacts(project_id: str = Query(...), _user=user_or_above):
    data = await repo.list_artifacts(project_id, owner_id=_user["sub"])
    if data is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return data


@router.get('/{artifact_id}')
async def get_artifact(artifact_id: str, _user=user_or_above):
    data = await repo.get_artifact(artifact_id, owner_id=_user["sub"])
    if not data:
        raise HTTPException(status_code=404, detail='Artifact not found')
    return data


@router.put('/{artifact_id}')
async def update_artifact(artifact_id: str, payload: ArtifactUpdate, _user=user_or_above):
    data = await repo.update_artifact(artifact_id, payload.content, owner_id=_user["sub"])
    if not data:
        raise HTTPException(status_code=404, detail='Artifact not found')
    return data


@router.post('/{artifact_id}/run')
async def run_artifact(artifact_id: str, _user=admin_or_above):
    """Execute the latest version of a Python artifact in the code sandbox.

    Double-gated: CODE_EXECUTION_ENABLED must be on (explicit deployment
    opt-in — the sandbox is a subprocess, not a container) and the caller
    must be admin or owner.
    """
    if not settings.code_execution_enabled:
        raise HTTPException(
            status_code=403,
            detail='Code execution is disabled. Set CODE_EXECUTION_ENABLED=true to enable it.',
        )
    data = await repo.get_artifact(artifact_id, owner_id=_user["sub"])
    if not data:
        raise HTTPException(status_code=404, detail='Artifact not found')
    versions = data.get('versions') or []
    content = versions[-1].get('content', '') if versions else ''
    if not content.strip():
        raise HTTPException(status_code=400, detail='Artifact is empty')

    from app.tools.code_sandbox import code_sandbox

    result = await code_sandbox.run_python(content)
    return {'artifact_id': artifact_id, 'version': len(versions), **result}
