from app.tools.registry import registry


async def run_deep_research(message: str, context: dict) -> dict:
    query_parts = [
        f"Background: {message}",
        f"Latest facts: {message}",
        f"Risks/tradeoffs: {message}",
    ]
    web_tool = registry.get("web_search")
    web_result = web_tool.handler({"query": message})
    return {
        "agent": "deep_research",
        "steps": query_parts,
        "web_search": web_result,
        "note": "Web search provider is currently a placeholder; citations may be limited until configured.",
    }
