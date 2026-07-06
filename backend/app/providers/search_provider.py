from __future__ import annotations
from typing import Protocol
import httpx
from app.core.config import settings


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> dict: ...


def _disabled(provider: str) -> dict:
    return {"configured": False, "provider": provider, "results": [], "message": "Web search is disabled."}


class DuckDuckGoSearchProvider:
    """Zero-config fallback using the DuckDuckGo instant-answer API.

    Free and keyless, but only returns encyclopedic "related topics" — many
    queries come back empty. Set TAVILY_API_KEY for real search results.
    """

    name = "duckduckgo"

    async def search(self, query: str, limit: int = 5) -> dict:
        if not settings.web_search_enabled:
            return _disabled(self.name)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1})
            r.raise_for_status()
            data = r.json()
        related = data.get("RelatedTopics", [])
        results = []
        for item in related:
            if isinstance(item, dict) and item.get("FirstURL"):
                results.append({"title": item.get("Text", ""), "url": item.get("FirstURL")})
            if len(results) >= limit:
                break
        return {"configured": True, "provider": self.name, "results": results}


class TavilySearchProvider:
    """Tavily search API (https://tavily.com) — purpose-built for LLM research.

    Returns real ranked web results with content snippets, so deep research
    gets useful evidence even before fetching the pages.
    """

    name = "tavily"

    async def search(self, query: str, limit: int = 5) -> dict:
        if not settings.web_search_enabled:
            return _disabled(self.name)
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": limit,
                    "include_answer": False,
                },
            )
            r.raise_for_status()
            data = r.json()
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:500],
            }
            for item in data.get("results", [])
            if item.get("url")
        ]
        return {"configured": True, "provider": self.name, "results": results}


def get_search_provider() -> SearchProvider:
    """Tavily when an API key is configured, DuckDuckGo otherwise."""
    if settings.tavily_api_key:
        return TavilySearchProvider()
    return search_provider


# Kept as a module-level singleton for existing imports.
search_provider = DuckDuckGoSearchProvider()
