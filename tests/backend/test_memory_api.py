from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_memory_save_search_delete():
    p = client.post('/api/project', json={'name': 'mem'}).json()
    m = client.post('/api/memory', json={'project_id': p['id'], 'user_id': 'u1', 'text': 'likes python and fastapi'}).json()
    hits = client.get(f"/api/memory/search?project_id={p['id']}&user_id=u1&q=python").json()
    assert hits
    d = client.delete(f"/api/memory/{m['id']}?user_id=u1").json()
    assert d['deleted'] is True
