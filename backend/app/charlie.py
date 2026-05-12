from dataclasses import dataclass, field
@dataclass
class CharlieResponse:
    text: str; trust_score: float=0.8; reasoning_depth: str='standard'; trace_id: str='demo'; elapsed_ms: float=0; tools_used: list=field(default_factory=list)
class CharlieAI:
    async def respond(self, message, session_id='default', user_id='local', user_role='user', stream_callback=None):
        text = f'Charlie AI received: {message}'
        if stream_callback:
            for word in text.split(): await stream_callback(word+' ')
        return CharlieResponse(text=text)
    async def project_status(self, project_path='/app'):
        from app.reality.project_scanner import status_report
        return status_report(project_path)
    async def execute_task(self, task, session_id='default', user_id='local', user_role='user'):
        return {'status': 'complete', 'result': f'Task accepted: {task}'}
