"""Async file ingestion: queued response, background pipeline, failure isolation."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_returns_immediately_with_queued_status():
    p = client.post('/api/project', json={'name': 'async-up'}).json()
    res = client.post(
        f"/api/files/upload?project_id={p['id']}",
        files={'file': ('doc.txt', b'water is wet\n' * 50, 'text/plain')},
    )
    assert res.status_code == 202
    body = res.json()
    # The response is sent before extraction/chunking run: no chunks yet.
    assert body['indexing_status'] == 'queued'
    assert body['chunks'] == []
    # TestClient executes the background task after the response, so by the
    # next request the pipeline has completed.
    status = client.get(f"/api/files/{body['id']}/status").json()
    assert status['indexing_status'] == 'ready'
    listed = client.get(f"/api/files/list?project_id={p['id']}").json()
    assert listed[0]['chunks'], 'chunks are produced by the background pipeline'


def test_unsupported_extension_rejected_synchronously():
    p = client.post('/api/project', json={'name': 'async-bad'}).json()
    res = client.post(
        f"/api/files/upload?project_id={p['id']}",
        files={'file': ('malware.exe', b'MZ...', 'application/octet-stream')},
    )
    assert res.status_code == 400
    assert 'Unsupported file type' in res.json()['detail']


def test_pdf_extraction_happens_in_background():
    p = client.post('/api/project', json={'name': 'async-pdf'}).json()
    # Not a real PDF — extract_text degrades to its "could not extract" note,
    # which must mark the file ready (not failed): a bad PDF is a content
    # problem, not a pipeline crash.
    res = client.post(
        f"/api/files/upload?project_id={p['id']}",
        files={'file': ('scan.pdf', b'%PDF-1.4 broken', 'application/pdf')},
    )
    assert res.status_code == 202
    status = client.get(f"/api/files/{res.json()['id']}/status").json()
    assert status['indexing_status'] == 'ready'
