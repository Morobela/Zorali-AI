"""Bounded web page fetcher for deep research.

Fetches a URL and reduces it to plain text the model can read as evidence.
Deliberately conservative: capped download size, capped extracted length,
HTML/text content types only, and every failure returns None instead of
raising — a dead link should cost the research pass one source, not the
whole answer.

No BeautifulSoup dependency: for evidence excerpts, dropping <script>/<style>
blocks and stripping tags is enough, and it keeps the requirements small.
"""
from __future__ import annotations

import html as html_lib
import logging
import re

import httpx

from app.core.config import settings

_log = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 1_000_000  # stop reading a response after ~1 MB

_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def html_to_text(html: str) -> str:
    """Strip an HTML document down to readable text."""
    text = _DROP_BLOCKS.sub(" ", html)
    # Block-level closers become line breaks so paragraphs stay separated.
    text = re.sub(r"</(p|div|li|h[1-6]|tr|section|article|br)>", "\n", text, flags=re.IGNORECASE)
    text = _TAGS.sub(" ", text)
    text = html_lib.unescape(text)
    text = _WHITESPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n", text).strip()


async def fetch_page_text(url: str, max_chars: int | None = None) -> str | None:
    """Fetch ``url`` and return its readable text, or None on any failure."""
    if not url.startswith(("http://", "https://")):
        return None
    limit = max_chars or settings.deep_research_page_chars
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers={"User-Agent": "Zorali-DeepResearch/1.0"}
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml")):
                    return None
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) >= MAX_DOWNLOAD_BYTES:
                        break
        body = raw.decode("utf-8", errors="ignore")
        text = html_to_text(body) if "html" in content_type else body.strip()
        return text[:limit] if text else None
    except Exception as exc:
        _log.info("Deep research fetch failed for %s: %s", url, exc)
        return None
