from app.agents.simple_chat import run_simple_chat
from app.agents.deep_research import run_deep_research
from app.agents.code_assistant import run_code_assistant
from app.agents.file_analysis import run_file_analysis
from app.agents.graph import GraphAgent
from app.orchestration.fault_tolerant import executor

_graph_agent = GraphAgent()


async def route_agent(mode: str, message: str, context: dict) -> dict:
    """
    Route to the appropriate agent and execute with fault-tolerant wrapper.

    Modes
    -----
    graph / tools   → GraphAgent  (LLM + tool-execution loop)
    deep_research   → DeepResearch
    code            → CodeAssistant
    file_analysis   → FileAnalysis
    <anything else> → SimpleChat  (direct response, no tools)

    "tools" is an alias for "graph" so callers can use either name when
    they want tool-capable execution.
    """
    async def _dispatch():
        if mode in ("graph", "tools"):
            history = context.get("history", [])
            messages = history + [{"role": "user", "content": message}]
            return await _graph_agent.run(message, messages=messages)
        if mode == "deep_research":
            return await run_deep_research(message, context)
        if mode == "code":
            return await run_code_assistant(message, context)
        if mode == "file_analysis":
            return await run_file_analysis(message, context)
        return await run_simple_chat(message, context)

    session = await executor.run(
        name=f"agent:{mode}",
        fn=_dispatch,
        max_attempts=3,
        base_delay=0.5,
    )
    if session.result is not None:
        return session.result
    try:
        return await run_simple_chat(message, context)
    except Exception:
        return {"plan": "direct_response", "mode": "fallback"}
