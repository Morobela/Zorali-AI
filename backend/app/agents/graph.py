"""
Agent execution graph.

Fix #5: The router function always falls back to "end" for any
        next_node value that isn't in the known set.  This prevents
        silent infinite loops when a node writes an unexpected value.
"""
from __future__ import annotations
from app.agents.types import AgentState
from app.agents.state import new_state
from app.agents.nodes import llm_node, tool_executor_node
from app.core.caller import Caller

# The complete set of valid routing targets.
_VALID_NODES = {"llm", "tools", "end"}


def _route(state: AgentState) -> str:
    """
    Routing function.

    Fix #5: Returns "end" for any next_node value outside _VALID_NODES
            so a buggy or hallucinated node name can never create a loop.
    """
    target = state.get("next_node", "end")
    if target not in _VALID_NODES:
        return "end"                       # FIX #5: safe fallback
    return target


class GraphAgent:
    """
    Minimal state-machine graph without an external framework dependency.

    Execution loop:
        llm → tools (if tool call) → llm (if retry) → end
        llm → end   (if direct answer or all retries exhausted)

    The _route() guard ensures we never spin forever on an unknown node.
    """

    _DISPATCH = None          # built lazily so circular-import risk is zero

    def _build_dispatch(self):
        return {
            "llm": llm_node.run,
            "tools": tool_executor_node.run,
        }

    async def run(
        self,
        task: str,
        messages: list[dict] | None = None,
        *,
        caller: Caller,
        caller_role: str = "user",
    ) -> dict:
        if self._DISPATCH is None:
            self.__class__._DISPATCH = self._build_dispatch()

        state = new_state(messages or [{"role": "user", "content": task}])
        # Caller context rides in the state so the tool-executor node can pass
        # it to registry.execute — tools are always invoked on someone's behalf.
        state["caller"] = caller
        state["caller_role"] = caller_role

        visited: list[str] = []
        max_steps = (state["max_retries"] + 1) * 4   # hard ceiling

        while len(visited) < max_steps:
            current = _route(state)
            if current == "end":
                break

            node_fn = self._DISPATCH.get(current)
            if node_fn is None:
                # Unknown node — FIX #5 guarantees we can't be here, but
                # belt-and-braces defence.
                break

            state = await node_fn(state)
            visited.append(current)

        return {
            "agent": "graph",
            "messages": state["messages"],
            "tool_results": state["tool_results"],
            "errors": state["errors"],
            "steps": visited,
            "retries": state["retry_count"],
        }
