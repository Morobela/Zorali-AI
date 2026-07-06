"""Deep research: multi-pass search → fetch → evidence, and the disabled path."""
import asyncio

import app.agents.deep_research as dr
from app.providers.web_fetcher import html_to_text


class _FakeProvider:
    name = "fake"

    def __init__(self, configured=True, results=None):
        self._configured = configured
        self._results = results or []

    async def search(self, query: str, limit: int = 5) -> dict:
        if not self._configured:
            return {"configured": False, "provider": self.name, "results": []}
        return {"configured": True, "provider": self.name, "results": self._results}


def test_disabled_search_returns_guidance(monkeypatch):
    monkeypatch.setattr(dr, "get_search_provider", lambda: _FakeProvider(configured=False))
    out = asyncio.run(dr.run_deep_research("what is pgvector", {}))
    assert out["agent"] == "deep_research"
    assert out["evidence"] == []
    assert "WEB_SEARCH_ENABLED" in out["message"]


def test_multipass_fetches_pages_and_builds_cited_evidence(monkeypatch):
    results = [
        {"title": "pgvector docs", "url": "https://example.com/pgvector", "snippet": "snippet A"},
        {"title": "dead link", "url": "https://example.com/404", "snippet": ""},
    ]
    monkeypatch.setattr(dr, "get_search_provider", lambda: _FakeProvider(results=results))

    async def fake_fetch(url, max_chars=None):
        return "pgvector is a Postgres extension for vector search" if "pgvector" in url else None

    monkeypatch.setattr(dr, "fetch_page_text", fake_fetch)

    out = asyncio.run(dr.run_deep_research("what is pgvector", {}))
    # Every selected source gets a [W#] citation, fetched or not…
    assert [c["marker"] for c in out["citations"]] == ["W1", "W2"]
    # …but only sources with content (fetched text or a snippet) become evidence.
    markers = {e["marker"]: e["excerpt"] for e in out["evidence"]}
    assert "Postgres extension" in markers["W1"]
    assert "W2" not in markers  # dead link with no snippet contributes nothing
    assert any("Synthesizing" in s for s in out["steps"])


def test_dead_page_falls_back_to_search_snippet(monkeypatch):
    results = [{"title": "t", "url": "https://example.com/x", "snippet": "fallback snippet"}]
    monkeypatch.setattr(dr, "get_search_provider", lambda: _FakeProvider(results=results))

    async def fake_fetch(url, max_chars=None):
        return None

    monkeypatch.setattr(dr, "fetch_page_text", fake_fetch)
    out = asyncio.run(dr.run_deep_research("q", {}))
    assert out["evidence"][0]["excerpt"] == "fallback snippet"


def test_html_to_text_strips_scripts_and_tags():
    html = """
    <html><head><title>x</title></head><body>
    <script>alert('evil')</script><style>body{}</style>
    <h1>Heading</h1><p>First paragraph.</p><p>Second &amp; last.</p>
    </body></html>
    """
    text = html_to_text(html)
    assert "alert" not in text
    assert "Heading" in text
    assert "First paragraph." in text
    assert "Second & last." in text
