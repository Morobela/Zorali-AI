"""A2A tasks are actually executed: submitted → running → completed/failed with a stored result."""
import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _poll_until_terminal(task_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f'/a2a/tasks/{task_id}')
        assert res.status_code == 200, res.text
        task = res.json()
        if task['status'] in ('completed', 'failed'):
            return task
        time.sleep(0.05)
    raise AssertionError(f'task {task_id} never reached a terminal status')


def test_submitted_task_executes_to_completion():
    res = client.post('/a2a/tasks/send', json={'message': 'ping from another agent'})
    assert res.status_code == 200
    body = res.json()
    assert body['status'] == 'submitted'

    task = _poll_until_terminal(body['task_id'])
    assert task['status'] == 'completed'
    assert task['result'] is not None
    assert task['error'] is None
    assert task['completed_at']


def test_a2a_message_parts_form_accepted():
    res = client.post('/a2a/tasks/send', json={
        'message': {'role': 'user', 'parts': [{'type': 'text', 'text': 'hello via parts'}]},
    })
    assert res.status_code == 200
    task = _poll_until_terminal(res.json()['task_id'])
    assert task['status'] == 'completed'


def test_failed_execution_is_recorded(monkeypatch):
    async def _boom(mode, message, context):
        raise RuntimeError('intentional agent failure')

    monkeypatch.setattr('app.a2a.endpoint.route_agent', _boom)
    res = client.post('/a2a/tasks/send', json={'message': 'this will fail'})
    task = _poll_until_terminal(res.json()['task_id'])
    assert task['status'] == 'failed'
    assert 'intentional agent failure' in task['error']
    assert task['result'] is None


def test_empty_message_rejected():
    assert client.post('/a2a/tasks/send', json={}).status_code == 400
    assert client.post('/a2a/tasks/send', json={'message': '   '}).status_code == 400
