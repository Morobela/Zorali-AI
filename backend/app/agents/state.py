"""
Agent state helpers — all mutations are copy-on-write.

Fix #2: Never mutate state lists in place.  Every helper returns a new
AgentState with a *copied* list, leaving the original untouched.  This
prevents one node's side-effects from silently bleeding into another.

Imports ONLY from types.py — never from nodes.py — to keep the import
graph acyclic (Fix #1).
"""
from __future__ import annotations
from app.agents.types import AgentState, ToolCall, ToolResult


def new_state(messages: list[dict] | None = None, max_retries: int = 3) -> AgentState:
    return AgentState.create(messages, max_retries=max_retries)


# ── Message helpers ───────────────────────────────────────────────────────────

def append_message(state: AgentState, role: str, content: str) -> AgentState:
    """Return new state with one message appended (copy-on-write)."""
    msgs = list(state["messages"])       # FIX #2: copy before append
    msgs.append({"role": role, "content": content})
    return AgentState({**state, "messages": msgs})


def prepend_system_message(state: AgentState, content: str) -> AgentState:
    """Inject a system message at the front (copy-on-write)."""
    msgs = list(state["messages"])       # FIX #2: copy before prepend
    msgs.insert(0, {"role": "system", "content": content})
    return AgentState({**state, "messages": msgs})


# ── Tool helpers ──────────────────────────────────────────────────────────────

def set_tool_calls(state: AgentState, calls: list[ToolCall]) -> AgentState:
    return AgentState({**state, "tool_calls": list(calls)})  # copy


def add_tool_result(state: AgentState, result: ToolResult) -> AgentState:
    results = list(state["tool_results"])    # FIX #2: copy
    results.append(result.to_dict())
    return AgentState({**state, "tool_results": results})


# ── Error helpers ─────────────────────────────────────────────────────────────

def add_error(state: AgentState, error: str) -> AgentState:
    errs = list(state["errors"])             # FIX #2: copy
    errs.append(error)
    return AgentState({**state, "errors": errs})


# ── Routing / control ─────────────────────────────────────────────────────────

def set_next(state: AgentState, node: str) -> AgentState:
    return AgentState({**state, "next_node": node})


def increment_retry(state: AgentState) -> AgentState:
    return AgentState({**state, "retry_count": state["retry_count"] + 1})


def reset_turn(state: AgentState) -> AgentState:
    """Clear per-turn tool data, keep messages and retry counter."""
    return AgentState({
        **state,
        "tool_calls": [],
        "tool_results": [],
        "errors": [],
        "next_node": "llm",
    })
