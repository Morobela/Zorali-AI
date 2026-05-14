from fastapi import APIRouter
router = APIRouter(prefix='/a2a')
@router.get('/.well-known/agent.json')
async def agent_card():
    return {'agent_id': 'zorali-ai-v1', 'name': 'Zorali AI', 'skills': ['chat','task_execution','project_status']}
@router.post('/tasks/send')
async def send_task(body: dict):
    return {'task_id':'demo-task','status':'submitted'}
@router.get('/tasks/{task_id}')
async def get_task(task_id: str):
    return {'task_id': task_id, 'status': 'completed', 'result': {'text': 'demo'}}
