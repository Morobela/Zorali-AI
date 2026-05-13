from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.db.repositories import repo

client = TestClient(app)


def test_project_and_chat_history():
    project = client.post('/api/project', json={'name': 'P1', 'description': 'd'}).json()
    assert project['id']
    chats = client.get(f"/api/project/{project['id']}/chats").json()
    assert isinstance(chats, list)


def test_artifact_versioning():
    project = client.post('/api/project', json={'name': 'P2'}).json()
    art = client.post('/api/artifacts', json={'project_id': project['id'], 'name': 'spec', 'content': 'v1'}).json()
    updated = client.put(f"/api/artifacts/{art['id']}", json={'content': 'v2'}).json()
    assert len(updated['versions']) == 2


def test_file_search_text_types():
    project = client.post('/api/project', json={'name': 'P3'}).json()
    files = {'file': ('note.txt', b'alpha beta gamma alpha', 'text/plain')}
    r = client.post(f"/api/files/upload?project_id={project['id']}", files=files)
    assert r.status_code == 200
    s = client.get(f"/api/files/search?project_id={project['id']}&q=alpha").json()
    assert len(s) >= 1


def test_upload_path_traversal_protection():
    project = client.post('/api/project', json={'name': 'P4'}).json()
    files = {'file': ('../evil.txt', b'harmful', 'text/plain')}
    response = client.post(f"/api/files/upload?project_id={project['id']}", files=files)
    assert response.status_code == 200
    payload = response.json()
    saved_path = Path(payload['path']).resolve()
    expected_root = (repo.upload_root / project['id']).resolve()
    assert expected_root in saved_path.parents
    assert saved_path.name != '../evil.txt'


def test_chat_rag_context_in_prompt(monkeypatch):
    captured = {}

    async def fake_stream_llm(messages):
        captured['messages'] = messages
        for token in ['ok']:
            yield token

    monkeypatch.setattr('app.api.chat.stream_llm', fake_stream_llm)

    project = client.post('/api/project', json={'name': 'P5'}).json()
    files = {'file': ('facts.txt', b'Paris is the capital of France', 'text/plain')}
    client.post(f"/api/files/upload?project_id={project['id']}", files=files)

    with client.websocket_connect('/ws/chat/test-session') as ws:
        ws.send_json({'mode': 'chat', 'project_id': project['id'], 'message': 'capital of France'})
        done = None
        while True:
            msg = ws.receive_json()
            if msg.get('type') == 'done':
                done = msg
                break

    assert done is not None
    assert done['citations'], 'citations should be returned only for retrieved chunks'
    sys_msgs = [m['content'] for m in captured['messages'] if m['role'] == 'system']
    assert any('Project file context:' in m and 'Paris is the capital of France' in m for m in sys_msgs)


def test_upload_rejects_malicious_project_id_and_no_escape_write():
    evil_dir = (repo.upload_root.resolve().parent / 'evil').resolve()
    if evil_dir.exists():
        for child in evil_dir.glob('**/*'):
            if child.is_file():
                child.unlink()
    files = {'file': ('note.txt', b'abc', 'text/plain')}
    response = client.post('/api/files/upload?project_id=../../evil', files=files)
    assert response.status_code == 400
    assert 'Invalid project_id path' in response.text
    assert not evil_dir.exists()
