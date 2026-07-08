"""Sandboxed code execution: sandbox behaviour, gating, and product surfaces."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.tools.code_sandbox import code_sandbox
from app.tools.registry import registry

client = TestClient(app)

from conftest import ws_ticket


def test_sandbox_runs_python_and_captures_output():
    out = asyncio.run(code_sandbox.run_python("print('hello from sandbox')"))
    assert out["returncode"] == 0
    assert "hello from sandbox" in out["stdout"]
    assert out["stderr"] == ""


def test_sandbox_reports_errors():
    out = asyncio.run(code_sandbox.run_python("raise ValueError('boom')"))
    assert out["returncode"] != 0
    assert "boom" in out["stderr"]


def test_sandbox_enforces_timeout():
    out = asyncio.run(code_sandbox.run_python("while True: pass", timeout=1))
    assert out["returncode"] == -1
    assert "timeout" in out["stderr"]


def test_sandbox_env_is_clean():
    # Server secrets must not leak into sandboxed code.
    out = asyncio.run(code_sandbox.run_python("import os; print(sorted(os.environ))"))
    assert "SECRET_KEY" not in out["stdout"]
    assert "POSTGRES_PASSWORD" not in out["stdout"]


def test_registry_tool_blocked_when_disabled():
    assert settings.code_execution_enabled is False
    with pytest.raises(PermissionError):
        asyncio.run(registry.execute("code_execution", {"code": "print(1)"}, actor_role="admin", caller="test-user"))


def test_registry_tool_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    out = asyncio.run(registry.execute("code_execution", {"code": "print(2+2)"}, actor_role="admin", caller="test-user"))
    assert out["returncode"] == 0
    assert "4" in out["stdout"]


def test_registry_tool_requires_admin_role(monkeypatch):
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    with pytest.raises(PermissionError):
        asyncio.run(registry.execute("code_execution", {"code": "print(1)"}, actor_role="user", caller="test-user"))


def test_artifact_run_endpoint_gated_by_setting():
    p = client.post('/api/project', json={'name': 'run-gate'}).json()
    art = client.post('/api/artifacts', json={'project_id': p['id'], 'name': 'calc.py', 'content': 'print(6*7)'}).json()
    res = client.post(f"/api/artifacts/{art['id']}/run")
    assert res.status_code == 403
    assert 'CODE_EXECUTION_ENABLED' in res.json()['detail']


def test_artifact_run_endpoint_executes_latest_version(monkeypatch):
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    p = client.post('/api/project', json={'name': 'run-ok'}).json()
    art = client.post('/api/artifacts', json={'project_id': p['id'], 'name': 'calc.py', 'content': 'print(6*7)'}).json()
    client.put(f"/api/artifacts/{art['id']}", json={'content': 'print(6*7+1)'})
    res = client.post(f"/api/artifacts/{art['id']}/run")
    assert res.status_code == 200
    body = res.json()
    assert body['returncode'] == 0
    assert '43' in body['stdout']
    assert body['version'] == 2


def test_ws_run_command_gated_then_runs(monkeypatch):
    p = client.post('/api/project', json={'name': 'run-ws'}).json()
    with client.websocket_connect(f'/ws/chat/run-ws?ticket={ws_ticket(client)}') as ws:
        ws.send_json({'mode': 'task', 'project_id': p['id'], 'message': '/run print(11*11)'})
        msg = ws.receive_json()
        assert msg['type'] == 'task_result'
        assert msg['data']['status'] == 'error'
        assert 'CODE_EXECUTION_ENABLED' in msg['data']['result']

    monkeypatch.setattr(settings, "code_execution_enabled", True)
    with client.websocket_connect(f'/ws/chat/run-ws2?ticket={ws_ticket(client)}') as ws:
        ws.send_json({'mode': 'task', 'project_id': p['id'], 'message': '/run print(11*11)'})
        msg = ws.receive_json()
        assert msg['data']['status'] == 'complete'
        assert '121' in msg['data']['result']
        assert 'code_sandbox' in msg['data']['tools_used']
