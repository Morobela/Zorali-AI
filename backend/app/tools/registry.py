from __future__ import annotations
import asyncio
import inspect
from typing import Any, Callable
from pydantic import BaseModel
import ast
import operator as op
from app.core.caller import Caller
from app.tools.file_tools import read_file, write_file
from app.core.audit import audit, AuditEvent
from app.core.hooks import global_hooks


class ToolSpec(BaseModel):
    name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable
    tags: list[str] = []
    requires_role: str = "user"
    approval_required: bool = False
    # Tools that touch per-user data declare needs_caller=True; the registry
    # then passes the caller context as the handler's second argument.
    needs_caller: bool = False

    model_config = {"arbitrary_types_allowed": True}


_ROLE_RANK = {"readonly": 0, "user": 1, "admin": 2, "owner": 3}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"Tool {name!r} not registered")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def get_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    async def execute(
        self,
        name: str,
        inputs: dict[str, Any],
        actor: str = "system",
        actor_role: str = "user",
        *,
        caller: Caller,
    ) -> dict[str, Any]:
        spec = self.get(name)

        # Enforce role requirement
        required_rank = _ROLE_RANK.get(spec.requires_role, 1)
        actor_rank = _ROLE_RANK.get(actor_role, 0)
        if actor_rank < required_rank:
            audit.record(AuditEvent.PERMISSION_DENIED, actor=actor, resource=name, outcome="role_insufficient",
                         required=spec.requires_role, actual=actor_role)
            raise PermissionError(f"Tool '{name}' requires role '{spec.requires_role}' (actor has '{actor_role}')")

        if spec.approval_required:
            audit.record(AuditEvent.TOOL_BLOCKED, actor=actor, resource=name, outcome="approval_required")
            raise PermissionError(f"Tool '{name}' requires explicit user approval before execution")

        async def _run():
            result = spec.handler(inputs, caller) if spec.needs_caller else spec.handler(inputs)
            # Await if the handler returned a coroutine (async handlers wrapped in sync lambdas)
            if inspect.isawaitable(result):
                result = await result
            return result

        try:
            result = await global_hooks.call_with_hooks(_run)
            audit.record(AuditEvent.TOOL_EXECUTED, actor=actor, resource=name, outcome="ok")
            return result
        except PermissionError:
            raise
        except Exception as exc:
            audit.record(AuditEvent.TOOL_BLOCKED, actor=actor, resource=name, outcome="error", error=str(exc))
            raise


def safe_calculate(expression: str) -> float:
    allowed = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow,
        ast.USub: op.neg,
    }

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](_eval(node.operand))
        raise ValueError("Unsupported expression")

    tree = ast.parse(expression, mode="eval")
    return float(_eval(tree.body))


registry = ToolRegistry()

registry.register(ToolSpec(
    name="calculator",
    input_schema={"expression": "string"},
    output_schema={"result": "number"},
    handler=lambda x: {"result": safe_calculate(x["expression"])},
    requires_role="user",
))

async def _web_search_tool(inputs: dict[str, Any]) -> dict[str, Any]:
    from app.providers.search_provider import get_search_provider

    return await get_search_provider().search(inputs["query"], limit=5)


registry.register(ToolSpec(
    name="web_search",
    input_schema={"query": "string"},
    output_schema={"results": "array"},
    # Live search via Tavily (TAVILY_API_KEY) or DuckDuckGo; respects WEB_SEARCH_ENABLED
    handler=lambda x: _web_search_tool(x),
    requires_role="user",
))

registry.register(ToolSpec(
    name="file_read",
    input_schema={"path": "string"},
    output_schema={"content": "string"},
    # read_file is async — the registry awaits coroutines automatically
    handler=lambda x: read_file(x["path"]),
    requires_role="user",
))

registry.register(ToolSpec(
    name="file_write",
    input_schema={"path": "string", "content": "string"},
    output_schema={"ok": "boolean"},
    handler=lambda x: write_file(x["path"], x["content"]),
    requires_role="admin",
    approval_required=True,
))

async def _code_execution_tool(inputs: dict[str, Any]) -> dict[str, Any]:
    from app.core.config import settings

    if not settings.code_execution_enabled:
        raise PermissionError("Code execution is disabled. Set CODE_EXECUTION_ENABLED=true to enable it.")
    from app.tools.code_sandbox import code_sandbox

    return await code_sandbox.run_python(inputs["code"])


registry.register(ToolSpec(
    name="code_execution",
    input_schema={"code": "string"},
    output_schema={"stdout": "string", "stderr": "string", "returncode": "int"},
    # Sandboxed `python -I` subprocess; the CODE_EXECUTION_ENABLED setting is
    # the explicit opt-in (checked inside the handler), the admin role gate
    # is defense in depth on top.
    handler=lambda x: _code_execution_tool(x),
    requires_role="admin",
))


async def _document_search_tool(inputs: dict[str, Any], caller: Caller) -> dict[str, Any]:
    from app.db.repositories import repo

    # Scoped to the calling user: a project they don't own looks empty,
    # exactly like the HTTP routes' 404 behaviour.
    hits = await repo.search_chunks(inputs["project_id"], inputs["query"], limit=5, owner_id=caller)
    return {"hits": hits or []}


registry.register(ToolSpec(
    name="document_search",
    input_schema={"project_id": "string", "query": "string"},
    output_schema={"hits": "array"},
    # Hybrid retrieval over the project's uploaded files
    handler=lambda x, c: _document_search_tool(x, c),
    requires_role="user",
    needs_caller=True,
))


def get_all_tools():
    return {name: spec.handler for name, spec in registry._tools.items()}
