from __future__ import annotations
from typing import Protocol
import httpx
from app.core.config import settings


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> dict: ...


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    async def search(self, query: str, limit: int = 5) -> dict:
        if not settings.web_search_enabled:
            return {"configured": False, "provider": self.name, "results": [], "message": "Web search is disabled."}
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


search_provider = DuckDuckGoSearchProvider()
