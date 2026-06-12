"""
Agent graph nodes.

Imports from types.py and state.py only — never the reverse — keeping
the import graph acyclic (Fix #1 from previous commit).

Fix #3: ToolExecutorNode wraps every tool.invoke() in try/except and
         stores errors in state instead of crashing silently.
Fix #4: ToolExecutorNode validates inputs against ToolSpec.input_schema
         with Pydantic before invoking any tool.
Fix #6: On retry, LLMNode prepends a failure summary to the messages so
         the model knows what went wrong and adjusts its next attempt.
"""
from __future__ import annotations
import json
import re
from typing import Any

from app.agents.types import AgentState, ToolCall, ToolResult
from app.agents.state import (
    append_message,
    prepend_system_message,
    set_tool_calls,
    add_tool_result,
    add_error,
    set_next,
    increment_retry,
)
from app.tools.registry import registry
from pydantic import BaseModel, ValidationError, create_model


# ── Input validation ──────────────────────────────────────────────────────────

_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "str": str,
    "number": float,
    "float": float,
    "int": int,
    "integer": int,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "object": dict,
}


def _build_pydantic_model(name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    """Build a throw-away Pydantic model from a ToolSpec input_schema dict."""
    fields: dict[str, Any] = {}
    for field_name, type_str in input_schema.items():
        python_type = _SCHEMA_TYPE_MAP.get(str(type_str).lower(), Any)
        fields[field_name] = (python_type, ...)
    return create_model(f"{name}Inputs", **fields)


def validate_tool_inputs(tool_name: str, inputs: dict[str, Any]) -> None:
    """
    Validate inputs against the registered ToolSpec's input_schema.
    Raises ValidationError (Pydantic) or ValueError on mismatch.
    """
    try:
        spec = registry.get(tool_name)
    except KeyError:
        raise ValueError(f"Tool {tool_name!r} is not registered")
    model = _build_pydantic_model(tool_name, spec.input_schema)
    model(**inputs)


# ── Tool-call parser ──────────────────────────────────────────────────────────

_TOOL_CALL_RE = re.compile(r'TOOL_CALL:\s*(\{)', re.DOTALL)


def _parse_tool_call(response: str) -> ToolCall | None:
    """
    Extract a structured tool call from the LLM response.

    Expected format (injected into system prompt so the model knows it):
        TOOL_CALL: {"tool": "<name>", "inputs": {<key>: <value>, ...}}

    Why this replaces the old startswith("{") heuristic:
    - A normal response that happens to contain JSON would not have the
      TOOL_CALL: prefix, so it is never misdetected as a tool call.
    - The prefix can appear anywhere in the response — preamble text is
      safely ignored.
    - Brace-counting extracts the complete JSON object even when values
      contain nested braces, which a simple startswith/endswith cannot do.
    """
    match = _TOOL_CALL_RE.search(response)
    if not match:
        return None

    # Walk forward from the opening brace, counting depth.
    start = match.start(1)
    text = response[start:]
    depth = 0
    end = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == 0:
        return None

    try:
        raw = json.loads(text[:end])
        if not isinstance(raw, dict) or "tool" not in raw:
            return None
        return ToolCall(name=raw["tool"], inputs=raw.get("inputs", {}))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


# ── Tool-aware system prompt builder ─────────────────────────────────────────

def _build_tools_system_prompt() -> str:
    """
    Build a system message that describes available tools and the exact
    format the LLM must use to call them.

    Previously, available_tools was constructed but never inserted into the
    messages sent to the provider.  This function fixes that omission.
    """
    tool_specs = registry.get_tools()
    if not tool_specs:
        return ""

    lines = ["You have access to the following tools:\n"]
    for spec in tool_specs:
        schema_str = ", ".join(f"{k}: {v}" for k, v in spec.input_schema.items())
        lines.append(f"  • {spec.name}({schema_str})")

    lines += [
        "",
        "To call a tool, output EXACTLY this on its own line (nothing else on that line):",
        '  TOOL_CALL: {"tool": "<tool_name>", "inputs": {<key>: <value>}}',
        "",
        "For a direct answer, reply normally — do NOT include TOOL_CALL.",
    ]
    return "\n".join(lines)


# ── LLM node ──────────────────────────────────────────────────────────────────

class LLMNode:
    """
    Calls the provider, injects the tools system prompt, and decides routing.

    Changes in this revision:
    - available_tools is now included in the system message sent to the LLM
      (previously it was built but never used).
    - Tool-call detection replaced with _parse_tool_call() which uses the
      TOOL_CALL: prefix format instead of the fragile startswith("{") check.
    - Fix #6 (retry): failure summary prepended before calling provider.
    """

    async def run(self, state: AgentState) -> AgentState:
        retry_count = state["retry_count"]
        errors = state["errors"]

        # Prepend failure context on retries (Fix #6)
        if retry_count > 0 and errors:
            failure_summary = (
                f"[Retry {retry_count}] Previous attempt failed with "
                f"{len(errors)} error(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
                + "\nPlease adjust your approach."
            )
            state = prepend_system_message(state, failure_summary)

        # Inject the tools system prompt so the LLM knows what tools exist
        # and exactly how to invoke them.
        tools_prompt = _build_tools_system_prompt()
        messages: list[dict] = list(state["messages"])  # copy
        if tools_prompt:
            # Insert at position 0 so it appears before the conversation.
            messages = [{"role": "system", "content": tools_prompt}] + messages

        from app.providers.provider_router import router as provider_router
        tokens: list[str] = []
        try:
            async for token, _ in provider_router.stream_chat(messages):
                tokens.append(token)
        except Exception as exc:
            state = add_error(state, f"LLM call failed: {exc}")
            state = set_next(state, "end")
            return state

        response = "".join(tokens).strip()
        state = append_message(state, "assistant", response)

        # Structured tool-call detection (replaces fragile startswith check)
        call = _parse_tool_call(response)
        if call is not None:
            state = set_tool_calls(state, [call])
            state = set_next(state, "tools")
        else:
            state = set_next(state, "end")

        return state


# ── Tool executor node ─────────────────────────────────────────────────────────

class ToolExecutorNode:
    """
    Runs every ToolCall in state["tool_calls"].

    Fix #3: Every tool call is wrapped in try/except — failures stored in state.
    Fix #4: Inputs validated against ToolSpec.input_schema before execution.
    """

    async def run(self, state: AgentState) -> AgentState:
        calls: list[dict] = state["tool_calls"]
        retry_count = state["retry_count"]
        max_retries = state["max_retries"]

        for raw_call in calls:
            call = ToolCall(**raw_call) if isinstance(raw_call, dict) else raw_call
            result: ToolResult

            # Fix #4 — validate before touching the handler
            try:
                validate_tool_inputs(call.name, call.inputs)
            except (ValidationError, ValueError) as exc:
                err_msg = f"Tool {call.name!r} input validation failed: {exc}"
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    output={},
                    error=err_msg,
                )
                state = add_tool_result(state, result)
                state = add_error(state, err_msg)
                continue

            # Fix #3 — wrap execution, store error in state on failure
            try:
                output = await registry.execute(call.name, call.inputs)
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    output=output,
                )
            except Exception as exc:
                err_msg = f"Tool {call.name!r} raised: {exc}"
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    output={},
                    error=err_msg,
                )
                state = add_error(state, err_msg)

            state = add_tool_result(state, result)

        has_errors = bool(state["errors"])
        if has_errors and retry_count < max_retries:
            state = increment_retry(state)
            state = set_next(state, "llm")
        else:
            state = set_next(state, "end")

        return state


# ── Singleton instances ────────────────────────────────────────────────────────

llm_node = LLMNode()
tool_executor_node = ToolExecutorNode()
