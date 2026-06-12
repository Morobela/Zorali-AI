"""
Agent graph nodes.

Imports from types.py and state.py only — never the reverse — keeping
the import graph acyclic (Fix #1).

Fix #3: ToolExecutorNode wraps every tool.invoke() in try/except and
         stores errors in state instead of crashing silently.
Fix #4: ToolExecutorNode validates inputs against ToolSpec.input_schema
         with Pydantic before invoking any tool.
Fix #6: On retry, LLMNode prepends a failure summary to the messages so
         the model knows what went wrong and adjusts its next attempt.
"""
from __future__ import annotations
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


# ── Input validation (Fix #4) ─────────────────────────────────────────────────

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
    """
    Build a throw-away Pydantic model from a ToolSpec input_schema dict.
    Schema format: {"field_name": "type_string", ...}
    """
    fields: dict[str, Any] = {}
    for field_name, type_str in input_schema.items():
        python_type = _SCHEMA_TYPE_MAP.get(str(type_str).lower(), Any)
        fields[field_name] = (python_type, ...)   # required field
    return create_model(f"{name}Inputs", **fields)


def validate_tool_inputs(tool_name: str, inputs: dict[str, Any]) -> None:
    """
    Validate inputs against the registered ToolSpec's input_schema.
    Raises ValidationError (Pydantic) on mismatch.
    Fix #4: called before every tool invocation.
    """
    try:
        spec = registry.get(tool_name)
    except KeyError:
        raise ValueError(f"Tool {tool_name!r} is not registered")
    model = _build_pydantic_model(tool_name, spec.input_schema)
    model(**inputs)  # raises ValidationError if inputs don't match


# ── LLM node ──────────────────────────────────────────────────────────────────

class LLMNode:
    """
    Calls the provider and decides what comes next.

    Fix #6: If this is a retry, prepend a system message that summarises
    prior errors so the model can correct course instead of repeating the
    same mistake.
    """

    async def run(self, state: AgentState) -> AgentState:
        retry_count = state["retry_count"]
        errors = state["errors"]

        # FIX #6 — tell the LLM what went wrong on previous attempts
        if retry_count > 0 and errors:
            failure_summary = (
                f"[Retry {retry_count}] Previous attempt failed with "
                f"{len(errors)} error(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
                + "\nPlease adjust your approach."
            )
            state = prepend_system_message(state, failure_summary)

        messages = state["messages"]
        tool_specs = registry.get_tools()
        available_tools = [
            {"name": s.name, "description": s.input_schema} for s in tool_specs
        ]

        # Call the provider (streaming collapsed to full response for node use)
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

        # Simple heuristic: if the response mentions a tool call JSON block,
        # route to tools; otherwise go to end.
        if response.startswith("{") and '"tool"' in response:
            import json as _json
            try:
                raw_call = _json.loads(response)
                call = ToolCall(
                    name=raw_call["tool"],
                    inputs=raw_call.get("inputs", {}),
                )
                state = set_tool_calls(state, [call])
                state = set_next(state, "tools")
            except Exception:
                state = set_next(state, "end")
        else:
            state = set_next(state, "end")

        return state


# ── Tool executor node ─────────────────────────────────────────────────────────

class ToolExecutorNode:
    """
    Runs every ToolCall in state["tool_calls"].

    Fix #3: Every tool call is wrapped in try/except.  Failures are stored
            as errors in state rather than crashing the graph silently.
    Fix #4: Inputs are validated against ToolSpec.input_schema before the
            handler is ever touched.
    """

    async def run(self, state: AgentState) -> AgentState:
        calls: list[dict] = state["tool_calls"]
        retry_count = state["retry_count"]
        max_retries = state["max_retries"]

        for raw_call in calls:
            call = ToolCall(**raw_call) if isinstance(raw_call, dict) else raw_call
            result: ToolResult

            # FIX #4 — validate inputs before calling the handler
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
                continue  # skip execution; don't abort the whole graph

            # FIX #3 — wrap execution in try/except, store error in state
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

        # Decide next step: retry if there were errors and budget remains
        has_errors = bool(state["errors"])
        if has_errors and retry_count < max_retries:
            state = increment_retry(state)
            state = set_next(state, "llm")   # go back to LLM with failure context
        else:
            state = set_next(state, "end")

        return state


# ── Singleton instances ────────────────────────────────────────────────────────

llm_node = LLMNode()
tool_executor_node = ToolExecutorNode()
