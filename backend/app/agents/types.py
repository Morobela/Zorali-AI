"""
Shared types for the agent graph.
Lives here — not in state.py or nodes.py — to eliminate circular imports.
Both state.py and nodes.py import from here; neither imports from the other.
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass, field
from uuid import uuid4


# ── Agent state ──────────────────────────────────────────────────────────────

class AgentState(dict):
    """
    Typed agent state.  Implemented as a dict subclass so it is JSON-
    serialisable and works with any graph framework without extra wiring.

    Fields
    ------
    messages        : conversation history (never mutated in-place, see state.py)
    tool_calls      : tool invocations requested by the LLM this turn
    tool_results    : results/errors returned by ToolExecutorNode
    errors          : execution errors accumulated across the turn
    next_node       : routing signal written by each node
    retry_count     : how many retries have been attempted so far
    max_retries     : ceiling on retries (default 3)
    """

    @classmethod
    def create(
        cls,
        messages: list[dict] | None = None,
        *,
        max_retries: int = 3,
    ) -> "AgentState":
        state = cls()
        state["messages"] = list(messages or [])
        state["tool_calls"] = []
        state["tool_results"] = []
        state["errors"] = []
        state["next_node"] = "llm"
        state["retry_count"] = 0
        state["max_retries"] = max_retries
        return state


# ── Tool call / result ────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    name: str
    inputs: dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid4())[:8])


@dataclass
class ToolResult:
    call_id: str
    tool_name: str
    output: dict[str, Any]
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "output": self.output,
            "error": self.error,
            "success": self.success,
        }
