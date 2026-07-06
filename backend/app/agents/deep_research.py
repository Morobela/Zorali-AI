"""Deep research agent: multi-pass search → fetch → evidence for synthesis.

Pass 1 — search: query the configured provider (Tavily when TAVILY_API_KEY is
set, DuckDuckGo instant answers otherwise).
Pass 2 — read: fetch the top hits concurrently and reduce each page to a
bounded plain-text excerpt (see web_fetcher — dead links are skipped, not
fatal).
Pass 3 — synthesize: the evidence is returned to the chat pipeline, which
injects it as an UNTRUSTED context block with [W1]/[W2] markers so the model
writes a source-cited answer, and the frontend receives the URLs as
``web_citations`` on the done frame.
"""
import asyncio

from app.core.config import settings
from app.providers.search_provider import get_search_provider
from app.providers.web_fetcher import fetch_page_text


async def run_deep_research(message: str, context: dict) -> dict:
    provider = get_search_provider()
    search = await provider.search(message, limit=max(settings.deep_research_max_pages * 2, 5))

    if not search.get("configured"):
        return {
            "agent": "deep_research",
            "steps": ["Web search is disabled"],
            "citations": [],
            "evidence": [],
            "message": "Deep Research needs live search. Set WEB_SEARCH_ENABLED=true "
                       "(and optionally TAVILY_API_KEY for richer results).",
        }

    results = search.get("results", [])[: settings.deep_research_max_pages]
    steps = [
        f"Searched ({search.get('provider')}): {message}",
        f"Selected top {len(results)} sources to read",
    ]

    # Pass 2: read the selected pages concurrently.
    texts = await asyncio.gather(*(fetch_page_text(r["url"]) for r in results))

    evidence = []
    citations = []
    for idx, (result, text) in enumerate(zip(results, texts), start=1):
        excerpt = text or result.get("snippet") or ""
        citation = {"marker": f"W{idx}", "title": result.get("title", ""), "url": result["url"]}
        citations.append(citation)
        if excerpt:
            evidence.append({**citation, "excerpt": excerpt})
    steps.append(f"Extracted evidence from {len(evidence)} of {len(results)} sources")
    steps.append("Synthesizing a cited answer from the evidence")

    return {
        "agent": "deep_research",
        "steps": steps,
        "citations": citations,
        "evidence": evidence,
        "message": f"Live web research completed via {search.get('provider')}.",
    }
