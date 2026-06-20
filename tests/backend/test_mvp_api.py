import os
from importlib import reload

from fastapi.testclient import TestClient

from app.main import app
from app.db import repositories as repos
from app.core.auth import create_access_token

client = TestClient(app)

_WS_TOKEN = create_access_token("test-user", "owner")


def test_health_endpoint():
    res = client.get('/api/health')
    assert res.status_code == 200


def test_project_create_and_list():
    client.post('/api/project', json={'name': 'proj', 'description': 'desc'})
    rows = client.get('/api/project').json()
    assert any(r['name'] == 'proj' for r in rows)


def test_upload_chunking_and_search_and_citations():
    p = client.post('/api/project', json={'name': 'files'}).json()
    payload = b'alpha bravo charlie\n' * 200
    up = client.post(f"/api/files/upload?project_id={p['id']}", files={'file': ('notes.txt', payload, 'text/plain')})
    assert up.status_code == 202
    assert len(up.json()['chunks']) > 1
    hits = client.get(f"/api/files/search?project_id={p['id']}&q=alpha notes").json()
    assert hits and {'file_id', 'filename', 'chunk_id', 'score'}.issubset(hits[0].keys())


def test_artifact_create_update_list():
    p = client.post('/api/project', json={'name': 'art'}).json()
    art = client.post('/api/artifacts', json={'project_id': p['id'], 'name': 'spec', 'content': 'v1'}).json()
    client.put(f"/api/artifacts/{art['id']}", json={'content': 'v2'})
    listed = client.get(f"/api/artifacts?project_id={p['id']}").json()
    assert listed and len(listed[0]['versions']) == 2


def test_chat_route_import_and_task_mode():
    with client.websocket_connect(f'/ws/chat/s1?token={_WS_TOKEN}') as ws:
      ws.send_json({'mode': 'task', 'project_id': 'default', 'message': '/help'})
      msg = ws.receive_json()
      assert msg['type'] == 'task_result'


def test_zorali_data_dir_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv('ZORALI_DATA_DIR', str(tmp_path))
    reload(repos)
    repo = repos.Repository()
    p = repo.create_project('persist')
    repo2 = repos.Repository()
    assert any(x['id'] == p['id'] for x in repo2.list_projects())
