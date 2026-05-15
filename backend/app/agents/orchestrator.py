from app.agents.simple_chat import run_simple_chat
from app.agents.deep_research import run_deep_research
from app.agents.code_assistant import run_code_assistant
from app.agents.file_analysis import run_file_analysis


async def route_agent(mode: str, message: str, context: dict) -> dict:
    if mode == "deep_research":
        return await run_deep_research(message, context)
    if mode == "code":
        return await run_code_assistant(message, context)
    if mode == "file_analysis":
        return await run_file_analysis(message, context)
    return await run_simple_chat(message, context)
