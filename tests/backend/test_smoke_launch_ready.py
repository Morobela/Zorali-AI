from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_normal_chat_smoke(monkeypatch):
    async def fake_stream(messages, **kwargs):
        yield "hello"
    monkeypatch.setattr('app.api.chat.stream_llm', fake_stream)
    p = client.post('/api/project', json={'name': 'smoke-chat'}).json()
    with client.websocket_connect('/ws/chat/smoke') as ws:
        ws.send_json({'mode': 'chat', 'project_id': p['id'], 'message': 'hi'})
        got_done = False
        for _ in range(10):
            m = ws.receive_json()
            if m.get('type') == 'done':
                got_done = True
                break
    assert got_done


def test_file_upload_and_question_smoke(monkeypatch):
    async def fake_stream(messages, **kwargs):
        yield "answer"
    monkeypatch.setattr('app.api.chat.stream_llm', fake_stream)
    p = client.post('/api/project', json={'name': 'smoke-file'}).json()
    files = {'file': ('facts.txt', b'Earth orbits the Sun', 'text/plain')}
    up = client.post(f"/api/files/upload?project_id={p['id']}", files=files)
    assert up.status_code == 202


def test_provider_status_smoke():
    r = client.get('/api/providers/status')
    assert r.status_code == 200
    assert 'ollama' in r.json()
