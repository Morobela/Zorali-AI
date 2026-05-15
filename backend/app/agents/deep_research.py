from app.providers.search_provider import search_provider


async def run_deep_research(message: str, context: dict) -> dict:
    steps = [
        f"Break down question: {message}",
        "Search external sources",
        "Synthesize findings with citations",
    ]
    search = await search_provider.search(message, limit=5)
    citations = [{"title": r["title"], "url": r["url"]} for r in search.get("results", [])]
    if not search.get("configured"):
        return {
            "agent": "deep_research",
            "steps": steps,
            "citations": [],
            "message": "Deep Research is configured as coming soon. Enable WEB_SEARCH_ENABLED=true to activate live search.",
        }
    return {
        "agent": "deep_research",
        "steps": steps,
        "citations": citations,
        "message": "Live web search completed.",
    }
