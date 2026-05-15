from __future__ import annotations
from typing import Any, Callable
from pydantic import BaseModel
from app.tools.file_tools import read_file, write_file


class ToolSpec(BaseModel):
    name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())


registry = ToolRegistry()
registry.register(ToolSpec(name="calculator", input_schema={"expression": "string"}, output_schema={"result": "number"}, handler=lambda x: {"result": eval(x["expression"], {"__builtins__": {}})}))
registry.register(ToolSpec(name="web_search", input_schema={"query": "string"}, output_schema={"results": "array"}, handler=lambda x: {"results": [], "note": "Provider not configured"}))
registry.register(ToolSpec(name="file_read", input_schema={"path": "string"}, output_schema={"content": "string"}, handler=lambda x: {"content": read_file(x["path"]) }))
registry.register(ToolSpec(name="file_write", input_schema={"path": "string", "content": "string"}, output_schema={"ok": "boolean"}, handler=lambda x: {"ok": write_file(x["path"], x["content"]) }))
registry.register(ToolSpec(name="code_execution", input_schema={"code": "string"}, output_schema={"output": "string"}, handler=lambda x: {"output": "sandbox placeholder"}))
registry.register(ToolSpec(name="document_search", input_schema={"project_id": "string", "query": "string"}, output_schema={"hits": "array"}, handler=lambda x: {"hits": []}))


def get_all_tools():
    return {name: spec.handler for name, spec in registry._tools.items()}
