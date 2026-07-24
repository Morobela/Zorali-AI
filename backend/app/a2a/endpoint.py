from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.agents.orchestrator import route_agent
from app.core.rbac import user_or_above

router = APIRouter(prefix='/a2a')

# Simple in-memory task store keyed by task_id
_tasks: dict[str, dict] = {}


def _extract_message(body: dict) -> str:
    """Accept a plain string or an A2A-style message object ({"parts": [{"text": …}]})."""
    message = body.get('message', '')
    if isinstance(message, dict):
        parts = message.get('parts', [])
        texts = [p.get('text', '') for p in parts if isinstance(p, dict)]
        return '\n'.join(t for t in texts if t).strip()
    return str(message).strip()


async def _execute_task(task_id: str, body: dict, owner_id: str, role: str) -> None:
    """Run a submitted task through the agent orchestrator and store the outcome."""
    task = _tasks.get(task_id)
    if task is None:
        return
    task['status'] = 'running'
    try:
        task['result'] = await route_agent(
            body.get('mode', 'chat'),
            _extract_message(body),
            {
                'project_id': body.get('project_id', 'default'),
                'attachments': [],
                'owner_id': owner_id,
                'role': role,
            },
        )
        task['status'] = 'completed'
    except Exception as exc:
        task['status'] = 'failed'
        task['error'] = str(exc)
    task['completed_at'] = datetime.now(timezone.utc).isoformat()


@router.get('/.well-known/agent.json')
async def agent_card():
    return {
        'agent_id': 'zorali-ai-v1',
        'name': 'Zorali',
        'version': '1.0.0',
        'skills': ['chat', 'task_execution', 'project_status', 'file_search', 'artifact_management'],
    }


@router.post('/tasks/send')
async def send_task(body: dict, background_tasks: BackgroundTasks, _user=user_or_above):
    if not _extract_message(body):
        raise HTTPException(status_code=400, detail='message is required')
    task_id = str(uuid4())
    _tasks[task_id] = {
        'task_id': task_id,
        'status': 'submitted',
        'input': body,
        'result': None,
        'error': None,
        # Results can contain the submitter's data, so reads are owner-scoped.
        'owner_id': _user['sub'],
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    # Execution is scoped to the submitting account, same as every other surface.
    background_tasks.add_task(_execute_task, task_id, body, _user['sub'], _user.get('role', 'user'))
    return {'task_id': task_id, 'status': 'submitted'}


@router.get('/tasks/{task_id}')
async def get_task(task_id: str, _user=user_or_above):
    task = _tasks.get(task_id)
    # A task submitted by someone else behaves like a nonexistent one.
    if not task or task['owner_id'] != _user['sub']:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.get('/tasks')
async def list_tasks(_user=user_or_above):
    return [t for t in _tasks.values() if t['owner_id'] == _user['sub']]
