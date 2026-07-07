"""
Tests for the agent graph layer.

Five scenarios required before PR #10 can leave draft:

  1. GraphAgent end-to-end run completes without errors
  2. Invalid tool input is stored in state["errors"] (not raised)
  3. A tool that raises an exception does not crash the graph
  4. An unknown next_node value routes safely to END
  5. Orchestrator routes mode="graph" / mode="tools" to GraphAgent

All LLM calls are intercepted with a monkeypatched async generator so
no real provider is required.
"""
from __future__ import annotations
import pytest
import pytest_asyncio

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fake_stream(*args, **kwargs):
    """Async-generator stub for provider_router.stream_chat."""
    yield ("Hello, ", "ollama")
    yield ("how can I help?", "ollama")


async def _fake_tool_call_stream(*args, **kwargs):
    """Stub that returns a well-formed TOOL_CALL response."""
    yield ('TOOL_CALL: {"tool": "calculator", "inputs": {"expression": "2+2"}}',
           "ollama")


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_route_unknown_node_returns_end():
    """_route() must fall back to 'end' for any unrecognised next_node value."""
    from app.agents.graph import _route
    from app.agents.state import new_state

    for bad_value in ("nonexistent", "", "LOOP_FOREVER", None, 42):
        state = new_state()
        state["next_node"] = bad_value
        assert _route(state) == "end", f"Expected 'end' for next_node={bad_value!r}"


def test_route_valid_nodes_pass_through():
    """Known node names must not be swallowed by the fallback."""
    from app.agents.graph import _route
    from app.agents.state import new_state

    for valid in ("llm", "tools"):
        state = new_state()
        state["next_node"] = valid
        assert _route(state) == valid


# ── Test 1 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_agent_runs_end_to_end(monkeypatch):
    """
    GraphAgent.run() must complete, return the expected shape, and produce
    no errors when the provider returns a plain-text (non-tool-call) response.
    """
    import app.providers.provider_router as pr_module
    monkeypatch.setattr(pr_module.router, "stream_chat", _fake_stream)

    from app.agents.graph import GraphAgent
    agent = GraphAgent()
    result = await agent.run("say hello", caller="test-user")

    assert result["agent"] == "graph"
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) >= 2          # user + assistant
    assert result["errors"] == []
    assert isinstance(result["steps"], list)


# ── Test 2 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_tool_input_stored_in_state_errors():
    """
    Calling a tool with wrong inputs must store a validation error in
    state["errors"] and must NOT raise an exception out of ToolExecutorNode.
    """
    from app.agents.nodes import ToolExecutorNode
    from app.agents.state import new_state

    state = new_state()
    state["caller"] = "test-user"
    # calculator expects {"expression": str} — supplying wrong key
    state["tool_calls"] = [
        {"name": "calculator", "inputs": {"wrong_key": "oops"}, "call_id": "t1"}
    ]

    node = ToolExecutorNode()
    result_state = await node.run(state)   # must not raise

    assert len(result_state["errors"]) > 0
    assert any("validation" in e.lower() for e in result_state["errors"])
    # Tool result entry must exist and carry the error
    assert len(result_state["tool_results"]) > 0
    assert result_state["tool_results"][0]["success"] is False


# ── Test 3 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_exception_does_not_crash_graph():
    """
    A tool that raises RuntimeError must not bubble out of ToolExecutorNode.
    The error must appear in state["errors"] and a failed ToolResult stored.
    """
    from app.agents.nodes import ToolExecutorNode
    from app.agents.state import new_state
    from app.tools.registry import registry, ToolSpec

    boom_name = "_test_boom_tool"
    registry.register(
        ToolSpec(
            name=boom_name,
            input_schema={"x": "string"},
            output_schema={"out": "string"},
            handler=lambda _: (_ for _ in ()).throw(RuntimeError("intentional boom")),
        )
    )

    state = new_state()
    state["caller"] = "test-user"
    state["tool_calls"] = [
        {"name": boom_name, "inputs": {"x": "trigger"}, "call_id": "t2"}
    ]

    node = ToolExecutorNode()
    result_state = await node.run(state)   # must not raise

    assert len(result_state["errors"]) > 0
    assert any("boom" in e.lower() or "raised" in e.lower()
               for e in result_state["errors"])
    assert result_state["tool_results"][0]["success"] is False


# ── Test 5 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_routes_graph_mode(monkeypatch):
    """
    route_agent(mode='graph') must call GraphAgent and return its result dict.
    """
    import app.providers.provider_router as pr_module
    monkeypatch.setattr(pr_module.router, "stream_chat", _fake_stream)

    from app.agents.orchestrator import route_agent
    result = await route_agent("graph", "hello from graph mode", {"project_id": "default", "owner_id": "test-user"})

    assert result.get("agent") == "graph"
    assert "messages" in result
    assert "errors" in result


@pytest.mark.asyncio
async def test_orchestrator_routes_tools_mode(monkeypatch):
    """
    'tools' is an alias for 'graph' — must also reach GraphAgent.
    """
    import app.providers.provider_router as pr_module
    monkeypatch.setattr(pr_module.router, "stream_chat", _fake_stream)

    from app.agents.orchestrator import route_agent
    result = await route_agent("tools", "use a tool please", {"project_id": "default", "owner_id": "test-user"})

    assert result.get("agent") == "graph"


# ── Bonus: parser unit-tests ──────────────────────────────────────────────────

def test_tool_call_parser_detects_valid_call():
    from app.agents.nodes import _parse_tool_call
    response = 'Sure!\nTOOL_CALL: {"tool": "calculator", "inputs": {"expression": "3*7"}}'
    call = _parse_tool_call(response)
    assert call is not None
    assert call.name == "calculator"
    assert call.inputs == {"expression": "3*7"}


def test_tool_call_parser_ignores_plain_json():
    from app.agents.nodes import _parse_tool_call
    # A normal reply that happens to contain JSON must NOT be detected
    response = 'Here is some JSON for you: {"tool": "example", "inputs": {}}'
    assert _parse_tool_call(response) is None


def test_tool_call_parser_returns_none_on_malformed():
    from app.agents.nodes import _parse_tool_call
    assert _parse_tool_call("TOOL_CALL: {broken json}") is None
    assert _parse_tool_call("") is None
    assert _parse_tool_call("just a normal sentence") is None
