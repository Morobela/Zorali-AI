from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix='/a2a')

# Simple in-memory task store keyed by task_id
_tasks: dict[str, dict] = {}


@router.get('/.well-known/agent.json')
async def agent_card():
    return {
        'agent_id': 'zorali-ai-v1',
        'name': 'Zorali AI',
        'version': '1.0.0',
        'skills': ['chat', 'task_execution', 'project_status', 'file_search', 'artifact_management'],
    }


@router.post('/tasks/send')
async def send_task(body: dict):
    task_id = str(uuid4())
    _tasks[task_id] = {
        'task_id': task_id,
        'status': 'submitted',
        'input': body,
        'result': None,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    return {'task_id': task_id, 'status': 'submitted'}


@router.get('/tasks/{task_id}')
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.get('/tasks')
async def list_tasks():
    return list(_tasks.values())

