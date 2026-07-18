"""MCP server honesty (Phase 6): the real tool registry over tools/list and
tools/call, with the ticket user's caller context and role enforced."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mcp.server import MCPServer
from conftest import ws_ticket

client = TestClient(app)


def test_tools_list_exposes_registry_over_ws():
    with client.websocket_connect(f"/mcp?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"method": "tools/list", "id": 7})
        reply = ws.receive_json()
    tools = {t["name"]: t for t in reply["result"]["tools"]}
    assert {"calculator", "web_search", "document_search", "code_execution", "file_write"} <= set(tools)
    calc = tools["calculator"]
    assert calc["inputSchema"]["properties"]["expression"]["type"] == "string"
    assert calc["inputSchema"]["required"] == ["expression"]


def test_tools_call_executes_through_registry():
    with client.websocket_connect(f"/mcp?ticket={ws_ticket(client)}") as ws:
        ws.send_json({
            "method": "tools/call", "id": 8,
            "params": {"name": "calculator", "arguments": {"expression": "2+2"}},
        })
        reply = ws.receive_json()
    result = reply["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"result": 4.0}


@pytest.mark.asyncio
async def test_role_gates_apply_to_mcp_calls():
    server = MCPServer()
    # Non-admin code_execution → clean tool error, not a crash.
    reply = await server.handle_message(
        {"method": "tools/call", "id": 1, "params": {"name": "code_execution", "arguments": {"code": "print(1)"}}},
        caller="some-user", caller_role="user",
    )
    assert reply["result"]["isError"] is True
    assert "requires role 'admin'" in reply["result"]["content"][0]["text"]
    # file_write stays approval-blocked even for admins.
    reply = await server.handle_message(
        {"method": "tools/call", "id": 2, "params": {"name": "file_write", "arguments": {"path": "x", "content": "y"}}},
        caller="some-admin", caller_role="admin",
    )
    assert reply["result"]["isError"] is True
    assert "approval" in reply["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_document_search_is_owner_scoped_over_mcp():
    from app.db.repositories import repo

    project = await repo.create_project("mcp-owned", owner_id="test-user")
    server = MCPServer()
    reply = await server.handle_message(
        {"method": "tools/call", "id": 3,
         "params": {"name": "document_search", "arguments": {"project_id": project["id"], "query": "anything"}}},
        caller="someone-else", caller_role="user",
    )
    assert reply["result"]["isError"] is False
    assert json.loads(reply["result"]["content"][0]["text"]) == {"hits": []}


@pytest.mark.asyncio
async def test_protocol_errors_are_jsonrpc_errors():
    server = MCPServer()
    unknown_method = await server.handle_message({"method": "resources/list", "id": 4})
    assert unknown_method["error"]["code"] == -32601
    unknown_tool = await server.handle_message(
        {"method": "tools/call", "id": 5, "params": {"name": "no_such_tool", "arguments": {}}}
    )
    assert unknown_tool["error"]["code"] == -32602
    bad_inputs = await server.handle_message(
        {"method": "tools/call", "id": 6, "params": {"name": "calculator", "arguments": {"wrong": "key"}}}
    )
    assert bad_inputs["result"]["isError"] is True
