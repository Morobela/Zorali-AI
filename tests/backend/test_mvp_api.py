import asyncio

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
    # Ingestion (extraction + chunking) is asynchronous: the response carries
    # the file id and a queued status; TestClient runs the background task
    # before the next request, after which chunks are searchable.
    body = up.json()
    assert body['indexing_status'] == 'queued'
    status = client.get(f"/api/files/{body['id']}/status").json()
    assert status['indexing_status'] == 'ready'
    listed = client.get(f"/api/files/list?project_id={p['id']}").json()
    assert len(listed[0]['chunks']) > 1
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


def test_repository_persists_across_instances():
    """Rows written through one Repository instance are visible from a fresh
    instance — persistence now lives in Postgres, not a per-instance JSON file."""
    repo = repos.Repository()
    p = asyncio.run(repo.create_project('persist'))
    repo2 = repos.Repository()
    assert any(x['id'] == p['id'] for x in asyncio.run(repo2.list_projects()))
