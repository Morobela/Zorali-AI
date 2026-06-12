from __future__ import annotations
from typing import Any, Callable
from pydantic import BaseModel
import ast
import operator as op
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


class ToolRegistry:
    """
    Enhanced tool registry.
    Patterns:
    - PyTorch: dict-based component registration
    - LangChain BaseToolkit: collection pattern with get_tools()
    - OpenJarvis SkillTool: bridges skill manifests to standard format
    - PyTorch hooks: pre/post hook on every tool execution
    """

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
        """LangChain BaseToolkit-style collection accessor."""
        return list(self._tools.values())

    async def execute(self, name: str, inputs: dict[str, Any], actor: str = "system") -> dict[str, Any]:
        """
        Execute a tool through the hook system.
        Pre-hook fires before execution, post-hook after.
        Audit records every tool call.
        """
        spec = self.get(name)

        async def _run():
            return spec.handler(inputs)

        try:
            result = await global_hooks.call_with_hooks(_run)
            audit.record(AuditEvent.TOOL_EXECUTED, actor=actor, resource=name, outcome="ok")
            return result
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
registry.register(ToolSpec(name="calculator", input_schema={"expression": "string"}, output_schema={"result": "number"}, handler=lambda x: {"result": safe_calculate(x["expression"]) }))
registry.register(ToolSpec(name="web_search", input_schema={"query": "string"}, output_schema={"results": "array"}, handler=lambda x: {"results": [], "note": "Coming soon: configure a web search provider"}))
registry.register(ToolSpec(name="file_read", input_schema={"path": "string"}, output_schema={"content": "string"}, handler=lambda x: {"content": read_file(x["path"]) }))
registry.register(ToolSpec(name="file_write", input_schema={"path": "string", "content": "string"}, output_schema={"ok": "boolean"}, handler=lambda x: {"ok": write_file(x["path"], x["content"]) }))
registry.register(ToolSpec(name="code_execution", input_schema={"code": "string"}, output_schema={"output": "string"}, handler=lambda x: {"output": "sandbox placeholder"}))
registry.register(ToolSpec(name="document_search", input_schema={"project_id": "string", "query": "string"}, output_schema={"hits": "array"}, handler=lambda x: {"hits": []}))


def get_all_tools():
    return {name: spec.handler for name, spec in registry._tools.items()}
