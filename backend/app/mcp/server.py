"""MCP server: the real tool registry over the Model Context Protocol.

``tools/list`` advertises every tool registered in ``app/tools/registry.py``
with a JSON-Schema input description; ``tools/call`` executes through
``registry.execute`` with the authenticated WebSocket user's caller context
and role — so the role gate on ``code_execution`` (admin + the
CODE_EXECUTION_ENABLED opt-in) and the approval block on ``file_write``
apply exactly as they do in chat. Tool failures come back MCP-style
(``result.isError: true``); unknown methods are JSON-RPC errors.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.caller import Caller
from app.tools.registry import registry

_JSON_TYPES = {
    "string": "string", "str": "string",
    "number": "number", "float": "number",
    "int": "integer", "integer": "integer",
    "boolean": "boolean", "bool": "boolean",
    "array": "array", "object": "object",
}


def _tool_descriptor(spec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": (
            f"Zorali tool '{spec.name}' (requires role: {spec.requires_role}"
            + (", needs explicit approval" if spec.approval_required else "")
            + ")"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                key: {"type": _JSON_TYPES.get(str(value).lower(), "string")}
                for key, value in spec.input_schema.items()
            },
            "required": list(spec.input_schema.keys()),
        },
    }


def _result(msg_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": payload}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_error(msg_id, message: str) -> dict:
    # MCP convention: tool-level failures are results with isError, so the
    # client model can read them; protocol failures are JSON-RPC errors.
    return _result(msg_id, {"content": [{"type": "text", "text": message}], "isError": True})


class MCPServer:
    async def handle_message(
        self,
        raw: dict,
        caller: Caller = "local",
        caller_role: str = "user",
    ) -> dict:
        method = raw.get("method")
        msg_id = raw.get("id")

        if method == "initialize":
            return _result(msg_id, {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "zorali-ai", "version": "2.0.0"},
                "capabilities": {"tools": {}},
            })

        if method == "tools/list":
            return _result(msg_id, {"tools": [_tool_descriptor(s) for s in registry.get_tools()]})

        if method == "tools/call":
            params = raw.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                return _error(msg_id, -32602, "tools/call requires params.name")
            try:
                registry.get(name)
            except KeyError:
                return _error(msg_id, -32602, f"Unknown tool: {name}")
            try:
                # Validate inputs against the ToolSpec schema before executing
                # (same guard the chat agent loop uses).
                from app.agents.nodes import validate_tool_inputs

                validate_tool_inputs(name, arguments if isinstance(arguments, dict) else {})
                output = await registry.execute(
                    name,
                    arguments,
                    actor=str(caller),
                    actor_role=caller_role,
                    caller=caller,
                )
            except Exception as exc:
                # PermissionError (role gate, approval block), validation
                # errors and tool bugs all surface as clean tool errors.
                return _tool_error(msg_id, str(exc))
            return _result(msg_id, {
                "content": [{"type": "text", "text": json.dumps(output, default=str)}],
                "isError": False,
            })

        return _error(msg_id, -32601, f"Method not found: {method}")
